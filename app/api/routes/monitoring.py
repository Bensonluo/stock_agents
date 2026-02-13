"""Monitoring and metrics endpoints."""

from typing import List, Optional

from fastapi import APIRouter, Query

from app.monitoring import AlertSeverity, get_monitor
from app.resilience import get_circuit_breaker_registry, get_retry_manager, get_time_limiter
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/health")
async def get_system_health():
    """Get overall system health.

    Returns:
        System health overview
    """
    monitor = get_monitor()
    return monitor.get_system_overview()


@router.get("/metrics")
async def get_metrics(agent_name: Optional[str] = None):
    """Get agent metrics.

    Args:
        agent_name: Optional filter for specific agent

    Returns:
        Agent metrics
    """
    monitor = get_monitor()
    return monitor.get_metrics(agent_name)


@router.get("/events")
async def get_events(
    agent_name: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
):
    """Get event log.

    Args:
        agent_name: Optional filter by agent name
        event_type: Optional filter by event type
        limit: Maximum number of events to return

    Returns:
        List of events
    """
    monitor = get_monitor()
    return monitor.get_events(agent_name, event_type, limit)


@router.get("/alerts")
async def get_alerts(
    severity: Optional[str] = None,
    agent_name: Optional[str] = None,
    active_only: bool = True,
    limit: int = Query(50, ge=1, le=500),
):
    """Get alerts.

    Args:
        severity: Optional filter by severity (low, medium, high, critical)
        agent_name: Optional filter by agent name
        active_only: Whether to return only active alerts
        limit: Maximum number of alerts to return

    Returns:
        List of alerts
    """
    monitor = get_monitor()

    # Convert severity string to enum if provided
    severity_enum = None
    if severity:
        try:
            severity_enum = AlertSeverity(severity.lower())
        except ValueError:
            pass

    return monitor.get_alerts(
        severity=severity_enum,
        agent_name=agent_name,
        active_only=active_only,
        limit=limit,
    )


@router.get("/circuit-breakers")
async def get_circuit_breakers():
    """Get circuit breaker status.

    Returns:
        Circuit breaker statistics
    """
    registry = get_circuit_breaker_registry()
    return registry.get_all_stats()


@router.get("/circuit-breakers/open")
async def get_open_circuits():
    """Get list of open circuit breakers.

    Returns:
        List of open circuit breaker names
    """
    registry = get_circuit_breaker_registry()
    open_circuits = registry.get_open_circuits()

    return {
        "open_circuits": open_circuits,
        "count": len(open_circuits),
    }


@router.post("/circuit-breakers/reset")
async def reset_circuit_breaker(name: Optional[str] = None):
    """Reset one or all circuit breakers.

    Args:
        name: Optional name of specific circuit breaker.
            If None, resets all circuit breakers.

    Returns:
        Reset confirmation
    """
    registry = get_circuit_breaker_registry()
    registry.reset(name)

    return {
        "status": "reset",
        "name": name if name else "all",
    }


@router.get("/retry/stats")
async def get_retry_stats():
    """Get retry statistics.

    Returns:
        Retry operation statistics
    """
    manager = get_retry_manager()
    return manager.get_retry_statistics()


@router.get("/retry/history")
async def get_retry_history(
    function_name: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
):
    """Get retry history.

    Args:
        function_name: Optional filter by function name
        limit: Maximum number of records to return

    Returns:
        Retry history
    """
    manager = get_retry_manager()
    return manager.get_retry_history(function_name, limit)


@router.get("/timeout/stats")
async def get_timeout_stats():
    """Get timeout statistics.

    Returns:
        Timeout operation statistics
    """
    limiter = get_time_limiter()
    return limiter.get_all_stats()


@router.post("/reset")
async def reset_monitoring():
    """Reset all monitoring data.

    Returns:
        Reset confirmation
    """
    monitor = get_monitor()
    monitor.reset_metrics()
    monitor.reset_events()
    monitor.reset_alerts()

    retry_manager = get_retry_manager()
    retry_manager.clear_history()

    time_limiter = get_time_limiter()
    time_limiter.reset_stats()

    return {
        "status": "reset",
        "timestamp": logger,
    }
