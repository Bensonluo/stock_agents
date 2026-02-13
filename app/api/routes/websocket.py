"""WebSocket endpoints for real-time agent monitoring.

This module provides WebSocket routes for live streaming of:
- Agent execution events (start, success, failure, timeout)
- System health updates
- Metric changes
- Alerts

The endpoint supports filtering by thread_id for multi-tenant scenarios.
"""

import asyncio
import json
from collections import deque
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field, ValidationError

from app.api.websocket import get_manager
from app.monitoring import get_monitor
from app.resilience import get_circuit_breaker_registry
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

# Heartbeat interval in seconds
HEARTBEAT_INTERVAL = 30

# Security: Maximum message size (1MB) to prevent DoS
MAX_MESSAGE_SIZE = 1024 * 1024

# Security: Rate limiting configuration
MAX_MESSAGES_PER_SECOND = 10
MAX_CONNECTIONS_PER_IP = 5
RATE_LIMIT_WINDOW = 1.0  # seconds

# Valid message types using Literal for strict type checking
ClientMessageType = Literal["subscribe", "unsubscribe", "set_filters", "ping"]


class ClientMessage(BaseModel):
    """Pydantic model for validating client messages.

    This provides strict input validation using Literal types
    to prevent injection attacks and malformed messages.
    """

    type: ClientMessageType = Field(
        ...,
        description="Message type from client",
    )
    data: dict[str, Any] | None = Field(
        default_factory=dict,
        description="Optional message payload",
    )


class ClientSubscription(BaseModel):
    """Client subscription preferences.

    Attributes:
        agent_names: Set of agent names to filter events (empty = all)
        event_types: Set of event types to filter (empty = all)
        min_severity: Minimum alert severity to receive
    """

    agent_names: set[str] = set()
    event_types: set[str] = set()
    min_severity: str = "low"


class WebSocketRateLimiter:
    """Rate limiter for WebSocket connections.

    Tracks message rate per connection and enforces limits
    to prevent DoS attacks through message flooding.
    """

    def __init__(self, max_messages: int = MAX_MESSAGES_PER_SECOND) -> None:
        """Initialize the rate limiter.

        Args:
            max_messages: Maximum messages allowed per time window
        """
        self.max_messages = max_messages
        self._timestamps: deque = deque()
        self._lock = asyncio.Lock()

    async def check_limit(self) -> bool:
        """Check if the message is within rate limits.

        Returns:
            True if message is allowed, False if rate limit exceeded
        """
        async with self._lock:
            now = asyncio.get_event_loop().time()

            # Remove timestamps outside the window
            while self._timestamps and now - self._timestamps[0] > RATE_LIMIT_WINDOW:
                self._timestamps.popleft()

            # Check if limit would be exceeded
            if len(self._timestamps) >= self.max_messages:
                return False

            # Add current timestamp
            self._timestamps.append(now)
            return True

    async def get_remaining(self) -> int:
        """Get remaining messages allowed in current window.

        Returns:
            Number of messages that can still be sent
        """
        async with self._lock:
            now = asyncio.get_event_loop().time()

            # Clean old timestamps
            while self._timestamps and now - self._timestamps[0] > RATE_LIMIT_WINDOW:
                self._timestamps.popleft()

            return max(0, self.max_messages - len(self._timestamps))


# Global IP connection tracker for per-IP connection limits
_ip_connections: dict[str, int] = {}
_ip_lock = asyncio.Lock()


async def _can_accept_ip(client_ip: str) -> bool:
    """Check if IP address is allowed to open a new connection.

    Args:
        client_ip: The client's IP address

    Returns:
        True if connection is allowed, False otherwise
    """
    async with _ip_lock:
        current_count = _ip_connections.get(client_ip, 0)
        if current_count >= MAX_CONNECTIONS_PER_IP:
            return False
        _ip_connections[client_ip] = current_count + 1
        return True


async def _release_ip(client_ip: str) -> None:
    """Release a connection slot for the given IP.

    Args:
        client_ip: The client's IP address
    """
    async with _ip_lock:
        current_count = _ip_connections.get(client_ip, 0)
        if current_count > 0:
            _ip_connections[client_ip] = current_count - 1
            if _ip_connections[client_ip] == 0:
                del _ip_connections[client_ip]


def _get_client_ip(websocket: WebSocket) -> str:
    """Extract client IP address from WebSocket connection.

    Args:
        websocket: The WebSocket connection

    Returns:
        The client's IP address as a string
    """
    # Try to get IP from headers first (for proxied connections)
    forwarded_for = websocket.headers.get("x-forwarded-for")
    if forwarded_for:
        # x-forwarded-for can contain multiple IPs, get the first one
        return forwarded_for.split(",")[0].strip()

    real_ip = websocket.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    # Fall back to the client address from the WebSocket
    if websocket.client and websocket.client.host:
        return websocket.client.host

    # Default if IP cannot be determined
    return "unknown"


async def send_initial_state(
    websocket: WebSocket,
    thread_id: str | None,
) -> None:
    """Send initial system state to a newly connected client.

    Args:
        websocket: The WebSocket connection
        thread_id: Optional thread identifier for filtering
    """
    try:
        monitor = get_monitor()
        circuit_registry = get_circuit_breaker_registry()

        # Gather initial state data
        system_overview = monitor.get_system_overview()
        agent_metrics = monitor.get_metrics()
        circuit_stats = circuit_registry.get_all_stats()
        active_alerts = monitor.get_alerts(active_only=True, limit=20)

        initial_message = {
            "type": "initial_state",
            "timestamp": datetime.now().isoformat(),
            "data": {
                "system_overview": system_overview,
                "agent_metrics": agent_metrics,
                "circuit_breakers": circuit_stats,
                "active_alerts": active_alerts,
                "thread_id": thread_id,
            },
        }

        await websocket.send_json(initial_message)
        logger.debug(f"Sent initial state to client thread_id={thread_id}")

    except Exception as e:
        logger.error(f"Failed to send initial state: {e}")


async def send_system_update(websocket: WebSocket) -> None:
    """Send a system status update.

    Args:
        websocket: The WebSocket connection
    """
    try:
        monitor = get_monitor()

        system_overview = monitor.get_system_overview()

        update_message = {
            "type": "system_update",
            "timestamp": datetime.now().isoformat(),
            "data": {
                "total_executions": system_overview["total_executions"],
                "overall_success_rate": system_overview["overall_success_rate"],
                "avg_health_score": system_overview["avg_health_score"],
                "total_agents": system_overview["total_agents"],
                "active_alerts": system_overview["active_alerts"],
            },
        }

        await websocket.send_json(update_message)

    except Exception as e:
        logger.error(f"Failed to send system update: {e}")


async def _send_error_response(
    websocket: WebSocket,
    message: str,
    close: bool = False,
) -> None:
    """Send a generic error response to the client.

    Security: Internal error details are never exposed to clients.

    Args:
        websocket: The WebSocket connection
        message: Generic error message to send
        close: Whether to close the connection after sending
    """
    error_response = {
        "type": "error",
        "timestamp": datetime.now().isoformat(),
        "data": {
            "message": message,
        },
    }

    if close:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=message)
    else:
        await websocket.send_json(error_response)


async def handle_client_message(
    message: dict[str, Any],
    websocket: WebSocket,
    subscription: ClientSubscription,
) -> None:
    """Handle a message received from the client.

    Args:
        message: The parsed message from client
        websocket: The WebSocket connection
        subscription: Current subscription state to update
    """
    message_type = message.get("type")

    if message_type == "subscribe":
        # Update subscription preferences
        data = message.get("data", {})
        if "agent_names" in data:
            subscription.agent_names = set(data["agent_names"])
        if "event_types" in data:
            subscription.event_types = set(data["event_types"])
        if "min_severity" in data:
            subscription.min_severity = data["min_severity"]

        await websocket.send_json({
            "type": "subscription_updated",
            "timestamp": datetime.now().isoformat(),
            "data": {
                "agent_names": list(subscription.agent_names),
                "event_types": list(subscription.event_types),
                "min_severity": subscription.min_severity,
            },
        })
        logger.debug(f"Updated subscription: {subscription}")

    elif message_type == "unsubscribe":
        # Clear all filters (receive everything)
        subscription.agent_names = set()
        subscription.event_types = set()
        subscription.min_severity = "low"

        await websocket.send_json({
            "type": "subscription_cleared",
            "timestamp": datetime.now().isoformat(),
        })
        logger.debug("Cleared subscription filters")

    elif message_type == "set_filters":
        # Set specific filters
        data = message.get("data", {})
        subscription.agent_names = set(data.get("agent_names", []))
        subscription.event_types = set(data.get("event_types", []))

        await websocket.send_json({
            "type": "filters_updated",
            "timestamp": datetime.now().isoformat(),
            "data": {
                "agent_names": list(subscription.agent_names),
                "event_types": list(subscription.event_types),
            },
        })
        logger.debug(f"Updated filters: {subscription}")

    elif message_type == "ping":
        # Respond to ping with pong
        await websocket.send_json({
            "type": "pong",
            "timestamp": datetime.now().isoformat(),
        })

    else:
        logger.warning(f"Unknown message type: {message_type}")


async def heartbeat_loop(websocket: WebSocket, thread_id: str | None) -> None:
    """Send periodic heartbeat messages to keep connection alive.

    Args:
        websocket: The WebSocket connection
        thread_id: Optional thread identifier
    """
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)

            heartbeat_message = {
                "type": "heartbeat",
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "thread_id": thread_id,
                },
            }

            await websocket.send_json(heartbeat_message)

    except asyncio.CancelledError:
        logger.debug("Heartbeat loop cancelled")
    except Exception as e:
        logger.error(f"Heartbeat loop error: {e}")


@router.websocket("/ws/monitoring")
async def websocket_monitoring_endpoint(
    websocket: WebSocket,
    thread_id: str | None = Query(
        None,
        description="Optional thread ID for filtering events",
    ),
):
    """WebSocket endpoint for real-time agent monitoring.

    This endpoint provides a persistent connection for receiving:
    - Initial system state on connection
    - Real-time agent lifecycle events
    - System health updates
    - Alert notifications
    - Periodic heartbeat messages

    Security Features:
    - Message size validation (max 1MB)
    - Rate limiting (10 messages/second per connection)
    - Connection limits (5 connections per IP)
    - Input validation with Pydantic
    - Generic error messages (no internal details exposed)

    Query Parameters:
        thread_id: Optional identifier for filtering events to a specific thread

    Client Message Format:
        {
            "type": "subscribe|unsubscribe|set_filters|ping",
            "data": { ... }
        }

    Server Message Format:
        {
            "type": "initial_state|agent_event|system_update|alert|heartbeat",
            "timestamp": "ISO 8601 timestamp",
            "data": { ... }
        }

    Example:
        // Connect with optional thread filter
        ws = new WebSocket("ws://localhost:8000/api/ws/monitoring?thread_id=analysis-123")

        // Subscribe to specific agents
        ws.send(JSON.stringify({
            "type": "subscribe",
            "data": {
                "agent_names": ["data_agent", "analysis_agent"],
                "event_types": ["agent_success", "agent_failure"],
                "min_severity": "medium"
            }
        }))
    """
    connection_manager = get_manager()
    heartbeat_task: asyncio.Task | None = None
    client_thread_id = thread_id
    rate_limiter = WebSocketRateLimiter()

    # Generate a unique connection ID
    connection_id = f"{client_thread_id or 'default'}_{datetime.now().timestamp()}"

    # Get client IP for rate limiting
    client_ip = _get_client_ip(websocket)

    try:
        # Security: Check IP connection limit before accepting
        if not await _can_accept_ip(client_ip):
            logger.warning(
                f"Connection rejected: IP limit exceeded for {client_ip}"
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # Accept the WebSocket connection
        await websocket.accept()

        logger.info(
            f"WebSocket connection established: connection_id={connection_id}, "
            f"thread_id={client_thread_id}, ip={client_ip}"
        )

        # Register with connection manager
        if client_thread_id:
            await connection_manager.connect(websocket, client_thread_id)
        else:
            # Generate a temporary thread_id for unfiltered connections
            client_thread_id = f"temp_{connection_id}"
            await connection_manager.connect(websocket, client_thread_id)

        # Initialize client subscription
        subscription = ClientSubscription()

        # Send initial system state
        await send_initial_state(websocket, client_thread_id)

        # Start heartbeat task
        heartbeat_task = asyncio.create_task(
            heartbeat_loop(websocket, client_thread_id)
        )

        # Main message loop
        while True:
            try:
                # Receive message from client
                raw_message = await websocket.receive_text()

                # Security: Validate message size before processing
                message_size = len(raw_message.encode('utf-8'))
                if message_size > MAX_MESSAGE_SIZE:
                    logger.warning(
                        f"Message rejected: size {message_size} exceeds limit "
                        f"{MAX_MESSAGE_SIZE} for connection_id={connection_id}"
                    )
                    await _send_error_response(
                        websocket,
                        "Message size exceeds maximum allowed",
                        close=True,
                    )
                    break

                # Security: Rate limiting check
                if not await rate_limiter.check_limit():
                    logger.warning(
                        f"Rate limit exceeded for connection_id={connection_id}"
                    )
                    await _send_error_response(
                        websocket,
                        "Rate limit exceeded. Please slow down.",
                        close=True,
                    )
                    break

                # Parse JSON message
                try:
                    message_dict = json.loads(raw_message)
                except json.JSONDecodeError:
                    await _send_error_response(
                        websocket,
                        "Invalid JSON format",
                    )
                    continue

                # Security: Validate message structure with Pydantic
                try:
                    client_message = ClientMessage(**message_dict)
                    message = client_message.model_dump()
                except ValidationError as e:
                    logger.warning(
                        f"Message validation failed: {e.errors()}"
                    )
                    await _send_error_response(
                        websocket,
                        "Invalid message format",
                    )
                    continue

                # Handle the message
                await handle_client_message(message, websocket, subscription)

                # Send a system update after client configuration changes
                if message.get("type") in ("subscribe", "unsubscribe", "set_filters"):
                    await send_system_update(websocket)

            except WebSocketDisconnect:
                logger.info(
                    f"WebSocket disconnected by client: connection_id={connection_id}"
                )
                break

            except Exception as e:
                logger.error(f"Error handling WebSocket message: {e}")
                # Security: Send generic error without exposing internal details
                await _send_error_response(
                    websocket,
                    "An error occurred processing your message",
                )

    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")

    finally:
        # Cancel heartbeat task
        if heartbeat_task and not heartbeat_task.done():
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

        # Disconnect from connection manager
        await connection_manager.disconnect(websocket, client_thread_id)

        # Release IP connection slot
        await _release_ip(client_ip)

        logger.info(
            f"WebSocket connection closed: connection_id={connection_id}, "
            f"thread_id={client_thread_id}"
        )


@router.get("/ws/connections")
async def get_active_connections():
    """Get information about active WebSocket connections.

    Returns:
        List of active connection information
    """
    manager = get_manager()

    active_thread_ids = await manager.get_active_thread_ids()
    connection_count = await manager.get_connection_count()

    return {
        "active_connections": connection_count,
        "active_thread_ids": active_thread_ids,
        "timestamp": datetime.now().isoformat(),
    }
