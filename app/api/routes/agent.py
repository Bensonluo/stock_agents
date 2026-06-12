"""API routes for the ReAct agent."""

import ast
import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from app.react_agent.react_agent import ReActAgent
from app.storage.database import AnalysisRecord, get_database
from app.tools.data.fetcher import fetch_stock_data
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])

_results: dict[str, dict[str, Any]] = {}
_progress_states: dict[str, dict[str, Any]] = {}

# Mark stale "running" records as failed on startup
try:
    _db = get_database()
    _stale = _db.list_records(limit=50, status="running")
    for _r in _stale:
        _db.update_status(_r.thread_id, "failed",
                          result=json.dumps({"answer": "Analysis interrupted by server restart"}),
                          execution_time=0)
        logger.info(f"Marked stale running record as failed: {_r.thread_id}")
except Exception:
    pass


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


class ProgressResponse(BaseModel):
    thread_id: str
    status: str
    iteration: int
    max_iterations: int
    tools_used: list[str]
    tool_call_history: list[dict]
    current_step: str
    started_at: str | None
    completed_at: str | None


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest, background_tasks: BackgroundTasks):
    """Start an autonomous stock analysis."""
    thread_id = f"react-{uuid.uuid4()}"
    background_tasks.add_task(
        _run_analysis,
        thread_id=thread_id,
        query=request.query,
        symbols=request.symbols,
        max_iterations=request.max_iterations,
    )
    return AnalyzeResponse(thread_id=thread_id, status="processing")


@router.get("/progress/{thread_id}", response_model=ProgressResponse)
async def get_progress(thread_id: str):
    """Get the progress of a running ReAct analysis."""
    progress = _progress_states.get(thread_id)
    if progress:
        return ProgressResponse(**progress)

    # If not in memory, check DB — if completed/failed, return that status
    try:
        db = get_database()
        record = db.get_record(thread_id)
        if record and record.status in ("completed", "failed"):
            stored = json.loads(record.result) if record.result else {}
            return ProgressResponse(
                thread_id=thread_id,
                status=record.status,
                iteration=stored.get("iterations", 0),
                max_iterations=15,
                tools_used=stored.get("tools_used", []),
                tool_call_history=[],
                current_step="completed" if record.status == "completed" else "failed",
                started_at=record.created_at,
                completed_at=record.updated_at,
            )
    except Exception:
        pass

    raise HTTPException(status_code=404, detail="Analysis not found")


async def _enrich_overview(answer: Any, symbols: list[str]) -> Any:
    """Server-side: patch the LLM's `answer` so overview.market_summary has
    real company_name / current_price / sector. The LLM often leaves these
    fields as None even though get_stock_overview returns the data, so we
    fetch the data ourselves and overwrite.

    The LLM emits a Python dict literal (single-quote, unquoted keys) rather
    than JSON, so we parse with ast.literal_eval and re-serialise the same way.
    """
    if not isinstance(answer, str) or not answer.strip():
        return answer
    try:
        parsed = ast.literal_eval(answer)
    except Exception:
        return answer  # not a Python literal; leave as-is
    if not isinstance(parsed, dict):
        return answer

    sections = parsed.setdefault("sections", {}) or {}
    overview = sections.setdefault("overview", {}) or {}
    ms = overview.setdefault("market_summary", {}) or {}

    async def _fill(sym: str) -> None:
        try:
            data = await fetch_stock_data(sym)
        except Exception:
            return
        if not data:
            return
        m = data.get("market_data", {}) or {}
        existing = ms.get(sym, {}) or {}
        if not existing.get("company_name"):
            existing["company_name"] = m.get("company_name")
        if existing.get("current_price") in (None, 0):
            existing["current_price"] = m.get("current_price")
        if not existing.get("sector"):
            existing["sector"] = m.get("sector")
        if existing.get("change") in (None,):
            existing["change"] = m.get("change")
        if existing.get("change_percent") in (None,):
            existing["change_percent"] = m.get("change_percent")
        if not existing.get("market_cap"):
            existing["market_cap"] = m.get("market_cap")
        ms[sym] = existing

    await asyncio.gather(*[_fill(s) for s in symbols if s])

    overview["market_summary"] = ms
    sections["overview"] = overview
    parsed["sections"] = sections

    # Re-serialise in the same style the LLM used (Python dict literal)
    return repr(parsed)


@router.get("/result/{thread_id}", response_model=ResultResponse)
async def get_result(thread_id: str):
    """Get the result of an analysis. Falls back to database if not in memory."""
    result = _results.get(thread_id)
    if result:
        answer = result.get("answer", "")
        symbols = (result.get("metadata") or {}).get("symbols") if isinstance(result.get("metadata"), dict) else None
        if not symbols and isinstance(answer, str):
            try:
                parsed = ast.literal_eval(answer)
                symbols = (parsed.get("metadata") or {}).get("symbols", []) if isinstance(parsed, dict) else []
            except Exception:
                symbols = []
        if symbols:
            answer = await _enrich_overview(answer, symbols)
            result = {**result, "answer": answer}
        return ResultResponse(**result)

    # Fallback: load from database (survives server restart)
    try:
        db = get_database()
        record = db.get_record(thread_id)
        if record and record.result:
            stored = json.loads(record.result)
            answer = stored.get("answer", "")
            symbols = (stored.get("metadata") or {}).get("symbols", []) if isinstance(stored.get("metadata"), dict) else []
            if not symbols and isinstance(answer, str):
                try:
                    parsed = ast.literal_eval(answer)
                    symbols = (parsed.get("metadata") or {}).get("symbols", []) if isinstance(parsed, dict) else []
                except Exception:
                    symbols = []
            if symbols:
                answer = await _enrich_overview(answer, symbols)
            return ResultResponse(
                answer=answer,
                report=stored.get("report"),
                iterations=stored.get("iterations", 0),
                tools_used=stored.get("tools_used", []),
                cost=stored.get("cost", 0),
            )
    except Exception as e:
        logger.warning(f"DB fallback failed for {thread_id}: {e}")

    raise HTTPException(status_code=404, detail="Analysis not found or still processing")


_STEP_MAP = {
    "agent_reason": "reasoning",
    "tool_execute": "executing_tools",
    "observe": "observing",
    "reflect": "reflecting",
}


def _save_to_db(thread_id: str, query: str, symbols: list[str], result: dict, status: str):
    """Persist analysis result to database for history."""
    try:
        db = get_database()
        now = datetime.now(timezone.utc).isoformat()

        result_data = {
            "answer": result.get("answer", ""),
            "report": result.get("report"),
            "iterations": result.get("iterations", 0),
            "tools_used": result.get("tools_used", []),
            "cost": result.get("cost", 0),
        }

        record = db.get_record(thread_id)
        if record:
            db.update_status(
                thread_id=thread_id,
                status=status,
                result=json.dumps(result_data, default=str),
                execution_time=0,
            )
        else:
            db.create_record(AnalysisRecord(
                thread_id=thread_id,
                symbols=json.dumps(symbols),
                query=query,
                status=status,
                result=json.dumps(result_data, default=str),
            ))
    except Exception as e:
        logger.warning(f"Failed to save to DB for {thread_id}: {e}")


async def _run_analysis(thread_id: str, query: str, symbols: list[str], max_iterations: int):
    """Run the analysis in the background."""
    _progress_states[thread_id] = {
        "thread_id": thread_id,
        "status": "processing",
        "iteration": 0,
        "max_iterations": max_iterations,
        "tools_used": [],
        "tool_call_history": [],
        "current_step": "starting",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
    }

    # Create DB record immediately
    _save_to_db(thread_id, query, symbols, {}, "running")

    async def on_node_complete(node_name: str, node_state: dict):
        progress = _progress_states.get(thread_id, {})
        progress["current_step"] = _STEP_MAP.get(node_name, node_name)
        progress["iteration"] = node_state.get("iteration", progress.get("iteration", 0))
        progress["tools_used"] = list(node_state.get("tools_used", progress.get("tools_used", [])))

        history = list(node_state.get("tool_call_history", progress.get("tool_call_history", [])))
        if history:
            progress["tool_call_history"] = [
                {"tool": h.get("tool", ""), "args": h.get("args", {}), "status": "completed"}
                for h in history
            ]

        _progress_states[thread_id] = progress

    try:
        agent = ReActAgent()
        result = await agent.analyze(
            query=query, symbols=symbols, thread_id=thread_id, progress_callback=on_node_complete,
        )
        _results[thread_id] = result
        _progress_states[thread_id]["status"] = "completed"
        _progress_states[thread_id]["current_step"] = "completed"
        _progress_states[thread_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
        _save_to_db(thread_id, query, symbols, result, "completed")
        logger.info(f"ReAct analysis complete for {thread_id}: {result['iterations']} iterations")
    except Exception as e:
        logger.error(f"ReAct analysis failed for {thread_id}: {e}")
        result = {
            "answer": f"Analysis failed: {str(e)}",
            "report": None,
            "iterations": 0,
            "tools_used": [],
            "cost": 0,
        }
        _results[thread_id] = result
        _progress_states[thread_id]["status"] = "failed"
        _progress_states[thread_id]["current_step"] = "failed"
        _progress_states[thread_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
        _save_to_db(thread_id, query, symbols, result, "failed")
