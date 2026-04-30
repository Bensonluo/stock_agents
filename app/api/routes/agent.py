"""API routes for the ReAct agent."""

import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from app.react_agent.react_agent import ReActAgent
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])

# In-memory result store (replace with database in production)
_results: dict[str, dict[str, Any]] = {}


class AnalyzeRequest(BaseModel):
    query: str = Field(description="User query")
    symbols: list[str] = Field(description="Stock symbols to analyze")
    max_iterations: int = Field(default=15, ge=1, le=50)


class AnalyzeResponse(BaseModel):
    thread_id: str
    status: str


class ResultResponse(BaseModel):
    answer: str
    report: dict | None
    iterations: int
    tools_used: list[str]
    cost: float


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    request: AnalyzeRequest,
    background_tasks: BackgroundTasks,
):
    """Start an autonomous stock analysis.

    The agent will autonomously fetch data, analyze, and generate a report.
    """
    thread_id = str(uuid.uuid4())

    background_tasks.add_task(
        _run_analysis,
        thread_id=thread_id,
        query=request.query,
        symbols=request.symbols,
        max_iterations=request.max_iterations,
    )

    return AnalyzeResponse(thread_id=thread_id, status="processing")


@router.get("/result/{thread_id}", response_model=ResultResponse)
async def get_result(thread_id: str):
    """Get the result of an analysis."""
    result = _results.get(thread_id)

    if not result:
        raise HTTPException(status_code=404, detail="Analysis not found or still processing")

    return ResultResponse(**result)


async def _run_analysis(
    thread_id: str,
    query: str,
    symbols: list[str],
    max_iterations: int,
):
    """Run the analysis in the background."""
    try:
        agent = ReActAgent()
        result = await agent.analyze(
            query=query,
            symbols=symbols,
            thread_id=thread_id,
        )
        _results[thread_id] = result
        logger.info(f"Analysis complete for {thread_id}: {result['iterations']} iterations")
    except Exception as e:
        logger.error(f"Analysis failed for {thread_id}: {e}")
        _results[thread_id] = {
            "answer": f"Analysis failed: {str(e)}",
            "report": None,
            "iterations": 0,
            "tools_used": [],
            "cost": 0,
        }
