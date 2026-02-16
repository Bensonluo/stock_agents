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


@router.get("/agents/{agent_name}/logs")
async def get_agent_logs(
    agent_name: str,
    thread_id: Optional[str] = None,
    level: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
):
    """Get agent execution logs.

    Args:
        agent_name: Name of the agent to get logs for
        thread_id: Optional filter by workflow thread ID
        level: Optional filter by log level (info, warning, error)
        limit: Maximum number of logs to return

    Returns:
        List of agent logs
    """
    monitor = get_monitor()

    # Get events filtered by agent name
    events = monitor.get_events(agent_name=agent_name, limit=1000)

    # Filter by thread_id if provided
    if thread_id:
        events = [
            e for e in events
            if e.get("data", {}).get("metadata", {}).get("thread_id") == thread_id
        ]

    # Filter by level if provided
    if level:
        level_lower = level.lower()
        level_event_types = {
            "info": ["agent_start", "agent_success", "agent_retry"],
            "warning": ["agent_retry"],
            "error": ["agent_failure", "agent_timeout"],
        }
        allowed_types = level_event_types.get(level_lower, [])
        if allowed_types:
            events = [e for e in events if e.get("event_type") in allowed_types]

    # Apply limit
    events = events[:limit]

    return {
        "agent_name": agent_name,
        "thread_id": thread_id,
        "level": level,
        "count": len(events),
        "logs": events,
    }


@router.get("/workflows/{thread_id}/logs")
async def get_workflow_logs(
    thread_id: str,
    limit: int = Query(500, ge=1, le=2000),
):
    """Get all logs for a workflow.

    Args:
        thread_id: Thread ID of the workflow
        limit: Maximum number of logs to return

    Returns:
        List of workflow logs
    """
    monitor = get_monitor()

    # Get all events
    all_events = monitor.get_events(limit=2000)

    # Filter by thread_id in data (direct or in metadata)
    workflow_events = [
        e for e in all_events
        if e.get("data", {}).get("thread_id") == thread_id or
           e.get("data", {}).get("metadata", {}).get("thread_id") == thread_id
    ]

    # Apply limit
    workflow_events = workflow_events[:limit]

    # Group by agent for summary
    agents_summary = {}
    for event in workflow_events:
        agent = event.get("agent", "unknown")
        event_type = event.get("event_type", "")
        if agent not in agents_summary:
            agents_summary[agent] = {
                "total": 0,
                "success": 0,
                "failure": 0,
                "timeout": 0,
            }
        agents_summary[agent]["total"] += 1
        if event_type == "agent_success":
            agents_summary[agent]["success"] += 1
        elif event_type == "agent_failure":
            agents_summary[agent]["failure"] += 1
        elif event_type == "agent_timeout":
            agents_summary[agent]["timeout"] += 1

    return {
        "thread_id": thread_id,
        "count": len(workflow_events),
        "agents_summary": agents_summary,
        "logs": workflow_events,
    }
