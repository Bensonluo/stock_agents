"""Main FastAPI application entry point."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import agent, analysis, backtest, health, monitoring
from app.api.routes import history as history_router
from app.api.routes import monitor as monitor_router
from app.api.routes import websocket as ws_router
from app.config import settings
from app.utils.logging import get_logger, setup_logging

# Setup logging
setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager.

    Handles startup and shutdown events.
    """
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")

    # Initialize components
    from app.monitoring import get_monitor
    from app.resilience import get_circuit_breaker_registry, get_retry_manager, get_time_limiter

    # Initialize global instances
    get_monitor()
    get_retry_manager()
    get_time_limiter()
    get_circuit_breaker_registry()

    logger.info("Application components initialized")

    # Opt-in daily watchlist scheduler (app/services/daily_run.py) — default
    # off, so lifespan behavior is unchanged until DAILY_RUN_ENABLED=true.
    daily_task: asyncio.Task | None = None
    if settings.daily_run_enabled:
        from app.services.daily_run import _next_run_at, daily_run_loop

        # Fail fast on a malformed DAILY_RUN_TIME: abandon the scheduler with
        # a clear error instead of a task that dies on its first scheduling.
        try:
            next_at = _next_run_at(datetime.now(), settings.daily_run_time)
        except ValueError as exc:
            logger.error(
                f"Invalid DAILY_RUN_TIME={settings.daily_run_time!r} ({exc}); "
                "daily watchlist run disabled"
            )
        else:
            daily_task = asyncio.create_task(daily_run_loop(), name="daily-watchlist-run")
            logger.info(f"Daily watchlist run enabled: next at {next_at.isoformat()}")

    yield

    if daily_task is not None:
        daily_task.cancel()
        try:
            await daily_task
        except asyncio.CancelledError:
            logger.info("Daily watchlist run scheduler stopped")
        except Exception as exc:
            logger.error(f"Daily watchlist run scheduler exited early: {exc}")

    logger.info("Shutting down application")

    # Release the orchestrator's resources (e.g., close the checkpoint DB).
    from app.api.dependencies import close_orchestrator

    await close_orchestrator()


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Multi-agent stock analysis system with LangGraph orchestration",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handlers
@app.exception_handler(ValueError)
async def value_error_handler(request, exc):
    """Handle ValueError exceptions."""
    return JSONResponse(
        status_code=400,
        content={"detail": str(exc)},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle general exceptions."""
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# Include routers
app.include_router(agent.router, prefix="/api", tags=["Agent"])
app.include_router(health.router, prefix="/api", tags=["Health"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["Analysis"])
app.include_router(backtest.router, prefix="/api/backtest", tags=["Backtest"])
app.include_router(history_router.router, prefix="/api/history", tags=["History"])
app.include_router(monitor_router.router, prefix="/api/monitor", tags=["Monitor"])
app.include_router(monitoring.router, prefix="/api/monitoring", tags=["Monitoring"])
app.include_router(ws_router.router, prefix="/api", tags=["WebSocket"])


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "description": "Multi-agent stock analysis system",
        "docs_url": "/docs",
        "endpoints": {
            "health": "/api/health",
            "analyze": "/api/analysis/analyze",
            "workflow_status": "/api/analysis/workflow/{thread_id}",
            "monitoring": "/api/monitoring/*",
            "backtest": "/api/backtest/*",
            "websocket": "/api/ws/monitoring",
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
