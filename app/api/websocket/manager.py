"""WebSocket connection manager for real-time monitoring.

This module provides a thread-safe connection manager for handling WebSocket
connections, enabling real-time data streaming to connected clients.

Core functionality:
- Manage active WebSocket connections with thread_id identification
- Broadcast messages to all connected clients
- Send targeted messages to specific threads
- Graceful handling of connection/disconnection
- Thread-safe operations using asyncio.Lock
"""

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import WebSocket, WebSocketDisconnect

from app.utils.logging import get_logger

logger = get_logger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections for real-time monitoring.

    This class provides thread-safe methods for:
    - Registering and unregistering WebSocket connections
    - Broadcasting messages to all connected clients
    - Sending messages to specific clients by thread_id
    - Tracking active connection count

    Example:
        manager = ConnectionManager()

        # In a WebSocket endpoint
        await manager.connect(websocket, thread_id="analysis-123")
        await manager.broadcast({"type": "update", "data": "..."})
        await manager.send_to_thread("analysis-123", {"type": "result"})
        await manager.disconnect(websocket)
    """

    def __init__(self) -> None:
        """Initialize the connection manager."""
        # Dict mapping thread_id to WebSocket connection
        self._connections: Dict[str, WebSocket] = {}
        # Lock for thread-safe access to connections
        self._lock: asyncio.Lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, thread_id: str) -> None:
        """Accept and register a new WebSocket connection.

        Args:
            websocket: The WebSocket connection to accept
            thread_id: Unique identifier for this connection/thread

        Raises:
            ValueError: If a connection with this thread_id already exists
        """
        await websocket.accept()

        async with self._lock:
            if thread_id in self._connections:
                logger.warning(
                    f"Connection already exists for thread_id: {thread_id}. "
                    f"Closing existing connection."
                )
                try:
                    await self._connections[thread_id].close()
                except Exception:
                    pass  # Best effort to close old connection

            self._connections[thread_id] = websocket

        connection_count = len(self._connections)
        logger.info(
            f"WebSocket connected: thread_id={thread_id}, "
            f"active_connections={connection_count}"
        )

    async def disconnect(self, websocket: WebSocket, thread_id: Optional[str] = None) -> None:
        """Remove a WebSocket connection from active connections.

        Args:
            websocket: The WebSocket connection to remove
            thread_id: Optional thread_id for faster lookup. If not provided,
                      searches for the connection by WebSocket object.
        """
        removed_thread_id = None

        async with self._lock:
            if thread_id and thread_id in self._connections:
                if self._connections[thread_id] == websocket:
                    removed_thread_id = thread_id
                    del self._connections[thread_id]
            else:
                # Search for the connection by WebSocket object
                for tid, ws in list(self._connections.items()):
                    if ws == websocket:
                        removed_thread_id = tid
                        del self._connections[tid]
                        break

        if removed_thread_id:
            connection_count = len(self._connections)
            logger.info(
                f"WebSocket disconnected: thread_id={removed_thread_id}, "
                f"active_connections={connection_count}"
            )
        else:
            logger.debug("WebSocket disconnect requested but connection not found")

    async def send_to_thread(
        self,
        thread_id: str,
        message: Dict[str, Any],
    ) -> bool:
        """Send a message to a specific thread/client.

        Args:
            thread_id: The identifier of the target thread
            message: The message payload to send (will be JSON serialized)

        Returns:
            True if message was sent successfully, False otherwise
        """
        async with self._lock:
            websocket = self._connections.get(thread_id)

        if not websocket:
            logger.debug(f"No connection found for thread_id: {thread_id}")
            return False

        try:
            await websocket.send_json(message)
            logger.debug(f"Sent message to thread_id={thread_id}: {message.get('type', 'unknown')}")
            return True
        except RuntimeError as e:
            # Connection might be closed
            logger.warning(f"Failed to send to thread_id={thread_id}: {e}")
            # Clean up the stale connection
            await self.disconnect(websocket, thread_id)
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending to thread_id={thread_id}: {e}")
            return False

    async def broadcast(
        self,
        message: Dict[str, Any],
        exclude_thread_id: Optional[str] = None,
    ) -> int:
        """Broadcast a message to all connected clients.

        Args:
            message: The message payload to send (will be JSON serialized)
            exclude_thread_id: Optional thread_id to exclude from broadcast

        Returns:
            Number of clients the message was sent to
        """
        async with self._lock:
            # Create a snapshot of connections to avoid holding lock during sends
            connections = list(self._connections.items())

        sent_count = 0
        failed_connections: List[str] = []

        for thread_id, websocket in connections:
            # Skip excluded thread
            if exclude_thread_id and thread_id == exclude_thread_id:
                continue

            try:
                await websocket.send_json(message)
                sent_count += 1
            except (RuntimeError, WebSocketDisconnect) as e:
                logger.warning(f"Broadcast failed for thread_id={thread_id}: {e}")
                failed_connections.append(thread_id)
            except Exception as e:
                logger.error(f"Unexpected broadcast error for thread_id={thread_id}: {e}")
                failed_connections.append(thread_id)

        # Clean up failed connections
        for thread_id in failed_connections:
            async with self._lock:
                if thread_id in self._connections:
                    del self._connections[thread_id]

        if sent_count > 0:
            logger.debug(
                f"Broadcast message type={message.get('type', 'unknown')} "
                f"to {sent_count} clients"
            )

        return sent_count

    async def get_connection_count(self) -> int:
        """Get the current number of active connections.

        Returns:
            Number of active WebSocket connections
        """
        async with self._lock:
            return len(self._connections)

    async def get_active_thread_ids(self) -> List[str]:
        """Get list of all active thread IDs.

        Returns:
            List of active thread_id strings
        """
        async with self._lock:
            return list(self._connections.keys())

    async def is_connected(self, thread_id: str) -> bool:
        """Check if a thread_id has an active connection.

        Args:
            thread_id: The thread_id to check

        Returns:
            True if thread_id has an active connection
        """
        async with self._lock:
            return thread_id in self._connections

    async def close_all(self) -> int:
        """Close all active WebSocket connections.

        This is useful for graceful shutdown scenarios.

        Returns:
            Number of connections closed
        """
        async with self._lock:
            connections = list(self._connections.items())

        closed_count = 0
        for thread_id, websocket in connections:
            try:
                await websocket.close()
                closed_count += 1
            except Exception as e:
                logger.warning(f"Error closing connection for thread_id={thread_id}: {e}")

        # Clear the connections dict
        async with self._lock:
            self._connections.clear()

        logger.info(f"Closed all WebSocket connections: {closed_count} connections")
        return closed_count


# Global connection manager instance
_manager: Optional[ConnectionManager] = None


def get_manager() -> ConnectionManager:
    """Get the global connection manager instance.

    Returns:
        The global ConnectionManager singleton instance
    """
    global _manager
    if _manager is None:
        _manager = ConnectionManager()
        logger.info("Initialized global WebSocket ConnectionManager")
    return _manager


def reset_manager() -> None:
    """Reset the global connection manager instance.

    This is primarily useful for testing purposes.
    """
    global _manager
    _manager = None
    logger.info("Reset global WebSocket ConnectionManager")
