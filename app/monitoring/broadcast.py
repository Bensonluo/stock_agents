"""WebSocket broadcast manager for real-time workflow updates."""

import json
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set

from fastapi import WebSocket

from app.utils.logging import get_logger

logger = get_logger(__name__)


class ConnectionManager:
    """WebSocket connection manager for broadcasting workflow events.

    This class provides:
    - WebSocket connection management
    - Thread-specific subscription support
    - Broadcast functionality for workflow events
    - Automatic cleanup of disconnected clients

    Core learning: Real-time event broadcasting in distributed systems.
    """

    def __init__(self):
        """Initialize the connection manager."""
        # thread_id -> set of WebSocket connections
        self._thread_subscribers: Dict[str, Set[WebSocket]] = defaultdict(set)
        # All connections (for global broadcasts)
        self._all_connections: Set[WebSocket] = set()
        # WebSocket -> thread_ids mapping (for cleanup)
        self._connection_threads: Dict[WebSocket, Set[str]] = defaultdict(set)

    async def connect(
        self,
        websocket: WebSocket,
        thread_id: Optional[str] = None,
    ) -> None:
        """Connect a new WebSocket client.

        Args:
            websocket: WebSocket connection
            thread_id: Optional thread ID to subscribe to specific workflows
        """
        await websocket.accept()
        self._all_connections.add(websocket)

        if thread_id:
            self._thread_subscribers[thread_id].add(websocket)
            self._connection_threads[websocket].add(thread_id)

        logger.debug(
            f"WebSocket connected: {id(websocket)}, "
            f"thread_id: {thread_id or 'all'}"
        )

    async def disconnect(self, websocket: WebSocket) -> None:
        """Disconnect a WebSocket client.

        Args:
            websocket: WebSocket connection to disconnect
        """
        # Remove from all connections
        self._all_connections.discard(websocket)

        # Remove from thread subscriptions
        if websocket in self._connection_threads:
            for thread_id in self._connection_threads[websocket]:
                self._thread_subscribers[thread_id].discard(websocket)
            del self._connection_threads[websocket]

        logger.debug(f"WebSocket disconnected: {id(websocket)}")

    async def subscribe(
        self,
        websocket: WebSocket,
        thread_id: str,
    ) -> None:
        """Subscribe a connection to a specific thread.

        Args:
            websocket: WebSocket connection
            thread_id: Thread ID to subscribe to
        """
        self._thread_subscribers[thread_id].add(websocket)
        self._connection_threads[websocket].add(thread_id)
        logger.debug(f"WebSocket {id(websocket)} subscribed to thread: {thread_id}")

    async def unsubscribe(
        self,
        websocket: WebSocket,
        thread_id: str,
    ) -> None:
        """Unsubscribe a connection from a specific thread.

        Args:
            websocket: WebSocket connection
            thread_id: Thread ID to unsubscribe from
        """
        self._thread_subscribers[thread_id].discard(websocket)
        self._connection_threads[websocket].discard(thread_id)
        logger.debug(f"WebSocket {id(websocket)} unsubscribed from thread: {thread_id}")

    async def broadcast(
        self,
        message: Dict[str, Any],
        thread_id: Optional[str] = None,
    ) -> None:
        """Broadcast a message to connected clients.

        Args:
            message: Message dictionary to broadcast
            thread_id: Optional thread ID for targeted broadcast.
                     If None, broadcasts to all connections.
        """
        # Serialize message once
        message_json = json.dumps(message)

        # Determine target connections
        if thread_id:
            # Thread-specific broadcast
            targets = self._thread_subscribers.get(thread_id, set())
        else:
            # Global broadcast
            targets = self._all_connections

        # Send to all target connections
        disconnected = set()
        for websocket in targets:
            try:
                await websocket.send_text(message_json)
            except Exception as e:
                logger.warning(f"Failed to send to websocket {id(websocket)}: {e}")
                disconnected.add(websocket)

        # Cleanup disconnected clients
        for websocket in disconnected:
            await self.disconnect(websocket)

    async def broadcast_agent_event(
        self,
        event_type: str,
        agent_name: str,
        thread_id: str,
        status: str,
        step: int,
        execution_time: Optional[float] = None,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Broadcast an agent lifecycle event.

        Args:
            event_type: Type of event (agent_start, agent_success, agent_failure)
            agent_name: Name of the agent
            thread_id: Workflow thread ID
            status: Agent status (running, completed, failed)
            step: Current workflow step number
            execution_time: Optional execution time in seconds
            error: Optional error message
            metadata: Optional additional metadata
        """
        message = {
            "type": event_type,
            "thread_id": thread_id,
            "agent_name": agent_name,
            "status": status,
            "step": step,
        }

        if execution_time is not None:
            message["execution_time"] = round(execution_time, 3)

        if error:
            message["error"] = error

        if metadata:
            message["metadata"] = metadata

        await self.broadcast(message, thread_id)

    async def broadcast_workflow_complete(
        self,
        thread_id: str,
        execution_time: float,
        success: bool,
        total_steps: int,
        error: Optional[str] = None,
    ) -> None:
        """Broadcast workflow completion event.

        Args:
            thread_id: Workflow thread ID
            execution_time: Total workflow execution time in seconds
            success: Whether workflow completed successfully
            total_steps: Number of steps completed
            error: Optional error message if failed
        """
        message = {
            "type": "workflow_complete",
            "thread_id": thread_id,
            "execution_time": round(execution_time, 3),
            "success": success,
            "total_steps": total_steps,
        }

        if error:
            message["error"] = error

        await self.broadcast(message, thread_id)

    def get_connection_count(self, thread_id: Optional[str] = None) -> int:
        """Get the number of active connections.

        Args:
            thread_id: Optional thread ID. If None, returns total connections.

        Returns:
            Number of active connections
        """
        if thread_id:
            return len(self._thread_subscribers.get(thread_id, set()))
        return len(self._all_connections)


# Global connection manager instance
_connection_manager: Optional[ConnectionManager] = None


def get_connection_manager() -> ConnectionManager:
    """Get the global connection manager instance.

    Returns:
        Global ConnectionManager instance
    """
    global _connection_manager
    if _connection_manager is None:
        _connection_manager = ConnectionManager()
    return _connection_manager


def reset_connection_manager() -> None:
    """Reset the global connection manager instance."""
    global _connection_manager
    _connection_manager = None
