"""Stock analysis endpoints."""

import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.dependencies import get_orchestrator
from app.monitoring.workflow_status import PIPELINE_AGENTS
from app.orchestration.state import AgentState
from app.utils.logging import get_logger
from app.utils.validators import validate_stock_symbol

logger = get_logger(__name__)

router = APIRouter()


# Request/Response Models
class StockAnalysisRequest(BaseModel):
    """Request model for stock analysis."""

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "query": "Analyze these stocks for investment potential",
                "symbols": ["AAPL", "MSFT", "GOOGL"],
                "max_retries": 3,
                "timeout_per_agent": 300,
            }
        },
    )

    query: str = Field(..., description="User's analysis query", min_length=1)
    symbols: list[str] = Field(..., description="List of stock symbols", min_length=1)
    max_retries: int = Field(default=3, ge=0, le=10, description="Maximum retry attempts")
    timeout_per_agent: int = Field(
        default=300, ge=10, le=600, description="Timeout per agent in seconds"
    )
    parallel_execution: bool = Field(default=True, description="Enable parallel execution")

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, symbols: list[str]) -> list[str]:
        """Validate stock symbols."""
        normalized = []
        for symbol in symbols:
            if not validate_stock_symbol(symbol):
                raise ValueError(f"Invalid stock symbol: {symbol}")
            normalized.append(symbol.upper())
        return normalized


class AnalysisResponse(BaseModel):
    """Response model for stock analysis."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "thread_id": "workflow-1234567890.123",
                "status": "completed",
                "message": "Analysis completed successfully",
            }
        }
    )

    thread_id: str
    status: str
    message: str
    report_url: str | None = None


class WorkflowStatusResponse(BaseModel):
    """Response model for workflow status."""

    thread_id: str
    current_step: int
    current_agent: str | None
    agent_status: dict
    has_errors: bool
    is_complete: bool


class AnalysisResultResponse(BaseModel):
    """Response model with full analysis results."""

    thread_id: str
    query: str
    symbols: list[str]
    technical_analysis: dict
    fundamental_analysis: dict
    sentiment_analysis: dict
    risk_assessment: dict
    decisions: dict
    report: dict
    execution_time: float
    timestamp: str


# In-memory workflow storage (in production, use database)
workflows: dict = {}

# Entries hold full analysis results (heavy); cap well below the status store.
MAX_TRACKED_API_WORKFLOWS = 50

# Analysis agents degrade gracefully and the pipeline still delivers a
# schema-compliant report; every other pipeline node is critical.
DEGRADABLE_AGENTS = {"technical_analysis", "fundamental_analysis", "sentiment_analysis"}
CRITICAL_AGENTS = set(PIPELINE_AGENTS) - DEGRADABLE_AGENTS


def _store_workflow(thread_id: str, entry: dict) -> None:
    """Insert a workflow entry, evicting when the cache is at capacity.

    Terminal entries (oldest completed/failed) go first; history remains
    queryable from the DB, so an evicted entry only degrades stale polls.
    """
    from app.utils.bounded_store import evict_oldest_terminal

    evict_oldest_terminal(
        workflows,
        MAX_TRACKED_API_WORKFLOWS,
        terminal_statuses=("completed", "failed", "partial"),
        timestamp_of=lambda e: e.get("completed_at") or e.get("started_at") or datetime.min,
    )
    workflows[thread_id] = entry


@router.post("/analyze", response_model=AnalysisResponse)
async def analyze_stocks(
    request: StockAnalysisRequest,
    background_tasks: BackgroundTasks,
) -> AnalysisResponse:
    """Analyze stocks using the multi-agent system.

    This endpoint:
    - Accepts a list of stock symbols and a query
    - Executes the multi-agent analysis workflow
    - Returns immediately with a thread_id for tracking

    Args:
        request: Analysis request

    Returns:
        Analysis response with thread_id
    """
    thread_id = f"workflow-{uuid.uuid4()}"

    logger.info(
        f"Starting analysis for symbols={request.symbols}, "
        f"query={request.query}, thread_id={thread_id}"
    )

    # Store initial workflow status
    _store_workflow(
        thread_id,
        {
            "status": "running",
            "request": request.model_dump(),
            "started_at": datetime.now(),
        },
    )

    # Execute workflow in background
    background_tasks.add_task(
        _execute_workflow,
        thread_id,
        request,
    )

    return AnalysisResponse(
        thread_id=thread_id,
        status="running",
        message=f"Analysis started for {len(request.symbols)} symbols",
        report_url=f"/api/analysis/result/{thread_id}",
    )


@router.get("/workflow/{thread_id}", response_model=WorkflowStatusResponse)
async def get_workflow_status(thread_id: str) -> WorkflowStatusResponse:
    """Get the status of an analysis workflow.

    Args:
        thread_id: Workflow thread ID

    Returns:
        Workflow status response
    """
    # Check if workflow exists
    workflow = workflows.get(thread_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Get status from stored workflow data
    agent_status = workflow.get("agent_status", {})
    current_agent = workflow.get("current_agent")
    current_step = workflow.get("current_step", 0)
    has_errors = workflow.get("has_errors", False)
    # A partial run is finished (degraded), not in flight.
    is_complete = workflow.get("status") in ("completed", "partial")

    return WorkflowStatusResponse(
        thread_id=thread_id,
        current_step=current_step,
        current_agent=current_agent,
        agent_status=agent_status,
        has_errors=has_errors,
        is_complete=is_complete,
    )


@router.get("/result/{thread_id}")
async def get_analysis_result(thread_id: str):
    """Get the full analysis result.

    Args:
        thread_id: Workflow thread ID

    Returns:
        Full analysis results
    """
    # Check workflow status
    workflow = workflows.get(thread_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if workflow["status"] == "running":
        raise HTTPException(
            status_code=202,
            detail="Analysis still in progress",
        )

    if workflow.get("error"):
        raise HTTPException(
            status_code=500,
            detail=workflow["error"],
        )

    result = workflow.get("result")
    if not result:
        raise HTTPException(
            status_code=404,
            detail="Result not available",
        )

    return result


@router.post("/analyze/sync")
async def analyze_stocks_sync(request: StockAnalysisRequest) -> AnalysisResultResponse:
    """Analyze stocks synchronously (waits for completion).

    This endpoint is similar to /analyze but waits for the workflow
    to complete before returning. Use this for quick analyses.

    Args:
        request: Analysis request

    Returns:
        Complete analysis results
    """
    from time import time

    start_time = time()
    thread_id = f"workflow-sync-{uuid.uuid4()}"

    logger.info(
        f"Starting sync analysis for symbols={request.symbols}, "
        f"query={request.query}, thread_id={thread_id}"
    )

    try:
        # Execute workflow
        result = await _execute_workflow_impl(
            thread_id,
            request.query,
            request.symbols,
            request.max_retries,
            request.timeout_per_agent,
            request.parallel_execution,
        )

        execution_time = time() - start_time

        # Store workflow
        _store_workflow(
            thread_id,
            {
                "status": "completed",
                "request": request.model_dump(),
                "result": result,
                "started_at": datetime.now(),
                "completed_at": datetime.now(),
            },
        )

        return AnalysisResultResponse(
            thread_id=thread_id,
            query=request.query,
            symbols=request.symbols,
            technical_analysis=result.get("technical_analysis", {}),
            fundamental_analysis=result.get("fundamental_analysis", {}),
            sentiment_analysis=result.get("sentiment_analysis", {}),
            risk_assessment=result.get("risk_assessment", {}),
            decisions=result.get("decision", {}).get("decisions", {}),
            report=result.get("report", {}),
            execution_time=execution_time,
            timestamp=datetime.now().isoformat(),
        )

    except Exception as e:
        logger.error(f"Sync analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Background task function
async def _execute_workflow(thread_id: str, request: StockAnalysisRequest):
    """Execute workflow in background.

    Args:
        thread_id: Workflow thread ID
        request: Analysis request
    """
    logger.info(f"Background task started for {thread_id}")
    try:
        result = await _execute_workflow_impl(
            thread_id,
            request.query,
            request.symbols,
            request.max_retries,
            request.timeout_per_agent,
            request.parallel_execution,
        )

        # Store result (guard: an eviction under cache pressure may have
        # dropped this entry mid-run; history still lands in the DB)
        entry = workflows.get(thread_id)
        if entry is not None:
            failed_any = any(
                status == "failed" for status in (result.get("agent_status") or {}).values()
            )
            # Mirror monitor/DB semantics: a degraded-but-finished run is
            # `partial` — its report exists and stays servable from
            # /result/{thread_id} instead of being overwritten by a 500 path.
            entry["status"] = "partial" if failed_any else "completed"
            entry["result"] = result
            entry["completed_at"] = datetime.now()

        logger.info(f"Workflow {thread_id} finished with status {entry and entry.get('status')}")
        logger.info(f"Final agent_status: {result.get('agent_status', {})}")

    except Exception as e:
        logger.error(f"Workflow {thread_id} failed: {e}")
        entry = workflows.get(thread_id)
        if entry is not None:
            entry["status"] = "failed"
            entry["error"] = str(e)
            entry["completed_at"] = datetime.now()


async def _execute_workflow_impl(
    thread_id: str,
    query: str,
    symbols: list[str],
    max_retries: int,
    timeout_per_agent: int,
    parallel_execution: bool,
) -> AgentState:
    """Execute the workflow implementation.

    Args:
        thread_id: Workflow thread ID
        query: Analysis query
        symbols: Stock symbols
        max_retries: Maximum retry attempts
        timeout_per_agent: Timeout per agent
        parallel_execution: Enable parallel execution

    Returns:
        Final agent state
    """
    orchestrator = get_orchestrator()

    result = await orchestrator.execute_workflow(
        query=query,
        symbols=symbols,
        thread_id=thread_id,
        max_retries=max_retries,
        timeout_per_agent=timeout_per_agent,
        parallel_execution=parallel_execution,
    )

    errors = result.get("errors", [])
    agent_status = result.get("agent_status", {})
    failed_agents = [name for name, status in agent_status.items() if status == "failed"]

    # Only pipeline-critical failures abort the request. Analysis agents
    # degrade gracefully: a run where sentiment failed but the report was
    # still generated is a partial success — raising here would 500 the
    # endpoint and hide a usable report that monitoring/DB already record
    # as `partial`. Transient errors that succeeded on retry likewise
    # leave records in `errors` without failing any agent.
    critical_failures = [name for name in failed_agents if name in CRITICAL_AGENTS]
    execution_error = result.get("execution_metadata", {}).get("error")
    if execution_error or critical_failures:
        detail = (
            execution_error
            if execution_error
            else f"Workflow failed in agents: {', '.join(critical_failures)}"
        )
        raise RuntimeError(detail)

    logger.info(f"Workflow {thread_id} result agent_status: {result.get('agent_status', {})}")

    workflow = workflows.get(thread_id)
    if workflow is None:  # evicted mid-run; recreate with a fresh timestamp
        workflow = {"status": "running", "started_at": datetime.now()}
        _store_workflow(thread_id, workflow)
    workflow["agent_status"] = agent_status
    workflow["current_agent"] = result.get("current_agent")
    workflow["current_step"] = result.get("current_step", 0)
    workflow["has_errors"] = bool(failed_agents or errors)

    logger.info(
        f"Updated workflows[{thread_id}] with agent_status: {workflows[thread_id].get('agent_status', {})}"
    )

    return result
