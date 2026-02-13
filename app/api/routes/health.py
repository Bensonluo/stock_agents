"""Health check endpoints."""

from datetime import datetime

from fastapi import APIRouter

from app.config import settings
from app.monitoring import get_monitor
from app.resilience import get_circuit_breaker_registry
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/health")
async def health_check():
    """Basic health check endpoint.

    Returns:
        Health status response
    """
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": settings.app_version,
    }


@router.get("/health/detailed")
async def detailed_health_check():
    """Detailed health check with component status.

    Returns:
        Detailed health status response
    """
    monitor = get_monitor()
    circuit_registry = get_circuit_breaker_registry()

    system_overview = monitor.get_system_overview()
    circuit_stats = circuit_registry.get_all_stats()
    open_circuits = circuit_registry.get_open_circuits()

    return {
        "status": "healthy" if not open_circuits else "degraded",
        "timestamp": datetime.now().isoformat(),
        "version": settings.app_version,
        "components": {
            "monitoring": {
                "status": "healthy",
                "total_executions": system_overview["total_executions"],
                "overall_success_rate": system_overview["overall_success_rate"],
            },
            "circuit_breakers": {
                "status": "healthy" if not open_circuits else "degraded",
                "total_circuits": len(circuit_stats),
                "open_circuits": len(open_circuits),
                "open_circuit_names": open_circuits,
            },
        },
        "system_overview": system_overview,
    }


@router.get("/health/ready")
async def readiness_check():
    """Readiness check for Kubernetes probes.

    Returns:
        Readiness status
    """
    # Could add checks for database connections, external APIs, etc.
    return {
        "ready": True,
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/health/live")
async def liveness_check():
    """Liveness check for Kubernetes probes.

    Returns:
        Liveness status
    """
    return {
        "alive": True,
        "timestamp": datetime.now().isoformat(),
    }
