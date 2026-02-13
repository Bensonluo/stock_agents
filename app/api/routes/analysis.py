"""Stock analysis endpoints."""

import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field, validator

from app.api.dependencies import get_orchestrator
from app.orchestration import MultiAgentOrchestrator
from app.orchestration.state import AgentState
from app.utils.logging import get_logger
from app.utils.validators import validate_stock_symbol

logger = get_logger(__name__)

router = APIRouter()


# Request/Response Models
class StockAnalysisRequest(BaseModel):
    """Request model for stock analysis."""

    query: str = Field(..., description="User's analysis query", min_length=1)
    symbols: List[str] = Field(..., description="List of stock symbols", min_items=1)
    max_retries: int = Field(default=3, ge=0, le=10, description="Maximum retry attempts")
    timeout_per_agent: int = Field(default=300, ge=10, le=600, description="Timeout per agent in seconds")
    parallel_execution: bool = Field(default=True, description="Enable parallel execution")

    @validator("symbols", each_item=True)
    def validate_symbols(cls, v):
        """Validate stock symbols."""
        if not validate_stock_symbol(v):
            raise ValueError(f"Invalid stock symbol: {v}")
        return v.upper()

    class Config:
        extra = "ignore"  # Ignore extra fields
        json_schema_extra = {
            "example": {
                "query": "Analyze these stocks for investment potential",
                "symbols": ["AAPL", "MSFT", "GOOGL"],
                "max_retries": 3,
                "timeout_per_agent": 300,
            }
        }


class AnalysisResponse(BaseModel):
    """Response model for stock analysis."""

    thread_id: str
    status: str
    message: str
    report_url: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "thread_id": "workflow-1234567890.123",
                "status": "completed",
                "message": "Analysis completed successfully",
            }
        }


class WorkflowStatusResponse(BaseModel):
    """Response model for workflow status."""

    thread_id: str
    current_step: int
    current_agent: Optional[str]
    agent_status: dict
    has_errors: bool
    is_complete: bool


class AnalysisResultResponse(BaseModel):
    """Response model with full analysis results."""

    thread_id: str
    query: str
    symbols: List[str]
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
    workflows[thread_id] = {
        "status": "running",
        "request": request.dict(),
        "started_at": datetime.now(),
    }

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
    is_complete = workflow.get("status") == "completed"

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
        workflows[thread_id] = {
            "status": "completed",
            "request": request.dict(),
            "result": result,
            "started_at": datetime.now(),
            "completed_at": datetime.now(),
        }

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


@router.get("/symbols/{symbol}")
async def get_symbol_data(symbol: str):
    """Get basic data for a single symbol.

    Args:
        symbol: Stock symbol

    Returns:
        Symbol data
    """
    # Validate symbol
    if not validate_stock_symbol(symbol):
        raise HTTPException(status_code=400, detail=f"Invalid stock symbol: {symbol}")

    symbol = symbol.upper()

    try:
        from app.services.data_service import DataService

        data_service = DataService()
        data = await data_service.get_quote(symbol)

        return {
            "symbol": symbol,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error(f"Error fetching data for {symbol}: {e}")
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

        # Store result
        workflows[thread_id]["status"] = "completed"
        workflows[thread_id]["result"] = result
        workflows[thread_id]["completed_at"] = datetime.now()

        logger.info(f"Workflow {thread_id} completed successfully")
        logger.info(f"Final agent_status: {result.get('agent_status', {})}")

    except Exception as e:
        logger.error(f"Workflow {thread_id} failed: {e}")
        workflows[thread_id]["status"] = "failed"
        workflows[thread_id]["error"] = str(e)
        workflows[thread_id]["completed_at"] = datetime.now()


async def _execute_workflow_impl(
    thread_id: str,
    query: str,
    symbols: List[str],
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

    logger.info(f"Workflow {thread_id} result agent_status: {result.get('agent_status', {})}")

    # Store workflow progress in shared dict
    workflows[thread_id]["agent_status"] = result.get("agent_status", {})
    workflows[thread_id]["current_agent"] = result.get("current_agent")
    workflows[thread_id]["current_step"] = result.get("current_step", 0)
    workflows[thread_id]["has_errors"] = len(result.get("errors", [])) > 0

    logger.info(f"Updated workflows[{thread_id}] with agent_status: {workflows[thread_id].get('agent_status', {})}")

    return result
