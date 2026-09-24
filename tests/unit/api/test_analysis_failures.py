from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.routes import analysis


@pytest.mark.asyncio
async def test_workflow_impl_rejects_failed_agent_state(monkeypatch) -> None:
    orchestrator = SimpleNamespace(
        execute_workflow=AsyncMock(
            return_value={
                "agent_status": {"data_collection": "failed"},
                "errors": [{"agent": "data_collection", "message": "provider down"}],
                "execution_metadata": {},
            }
        )
    )
    monkeypatch.setattr(analysis, "get_orchestrator", lambda: orchestrator)

    with pytest.raises(RuntimeError, match="data_collection"):
        await analysis._execute_workflow_impl(
            "failed-thread",
            "analyze",
            ["AAPL"],
            3,
            300,
            True,
        )


@pytest.mark.asyncio
async def test_background_workflow_records_failure(monkeypatch) -> None:
    request = analysis.StockAnalysisRequest(query="analyze", symbols=["AAPL"])
    analysis.workflows["failed-background"] = {"status": "running"}
    monkeypatch.setattr(
        analysis,
        "_execute_workflow_impl",
        AsyncMock(side_effect=RuntimeError("workflow exploded")),
    )

    await analysis._execute_workflow("failed-background", request)

    workflow = analysis.workflows["failed-background"]
    assert workflow["status"] == "failed"
    assert workflow["error"] == "workflow exploded"


def _full_status(degraded: str | None = None) -> dict:
    return {
        name: ("failed" if name == degraded else "completed")
        for name in (
            "data_collection",
            "technical_analysis",
            "fundamental_analysis",
            "sentiment_analysis",
            "risk_assessment",
            "research_synthesis",
            "decision_making",
            "report_generation",
        )
    }


@pytest.mark.asyncio
async def test_workflow_impl_allows_degraded_analysis_agents(monkeypatch) -> None:
    """Analysis-agent failure = degraded success: no raise, entry reflects it."""
    orchestrator = SimpleNamespace(
        execute_workflow=AsyncMock(
            return_value={
                "agent_status": _full_status(degraded="sentiment_analysis"),
                "errors": [{"agent": "sentiment_analysis", "message": "news feed down"}],
                "execution_metadata": {},
                "report": {"title": "partial report"},
            }
        )
    )
    monkeypatch.setattr(analysis, "get_orchestrator", lambda: orchestrator)
    analysis.workflows.pop("degraded-thread", None)

    result = await analysis._execute_workflow_impl(
        "degraded-thread",
        "analyze",
        ["AAPL"],
        3,
        300,
        True,
    )

    assert result["agent_status"]["sentiment_analysis"] == "failed"  # no raise, report flows
    entry = analysis.workflows["degraded-thread"]
    assert entry["has_errors"] is True
    analysis.workflows.pop("degraded-thread", None)


@pytest.mark.asyncio
async def test_workflow_impl_transien_errors_recovered_on_retry_do_not_fail(monkeypatch) -> None:
    """`errors` records survive a successful retry; the run itself is fine."""
    orchestrator = SimpleNamespace(
        execute_workflow=AsyncMock(
            return_value={
                "agent_status": _full_status(),  # everything completed
                "errors": [{"agent": "technical_analysis", "message": "transient"}],
                "execution_metadata": {},
            }
        )
    )
    monkeypatch.setattr(analysis, "get_orchestrator", lambda: orchestrator)
    analysis.workflows.pop("recovered-thread", None)

    result = await analysis._execute_workflow_impl(
        "recovered-thread",
        "analyze",
        ["AAPL"],
        3,
        300,
        True,
    )

    assert result["execution_metadata"] == {}
    assert analysis.workflows["recovered-thread"]["has_errors"] is True
    analysis.workflows.pop("recovered-thread", None)


@pytest.mark.asyncio
async def test_background_workflow_marks_degraded_run_partial(monkeypatch) -> None:
    """Degraded-but-finished runs surface as `partial` with a servable result."""
    request = analysis.StockAnalysisRequest(query="analyze", symbols=["AAPL"])
    analysis.workflows["degraded-run"] = {"status": "running"}
    monkeypatch.setattr(
        analysis,
        "_execute_workflow_impl",
        AsyncMock(
            return_value={
                "agent_status": _full_status(degraded="sentiment_analysis"),
                "execution_metadata": {},
                "report": {"title": "partial report"},
            }
        ),
    )

    await analysis._execute_workflow("degraded-run", request)

    entry = analysis.workflows["degraded-run"]
    assert entry["status"] == "partial"
    assert entry["result"]["report"] == {"title": "partial report"}
    assert "error" not in entry
    analysis.workflows.pop("degraded-run", None)


@pytest.mark.asyncio
async def test_background_workflow_clean_run_completes(monkeypatch) -> None:
    request = analysis.StockAnalysisRequest(query="analyze", symbols=["AAPL"])
    analysis.workflows["clean-run"] = {"status": "running"}
    monkeypatch.setattr(
        analysis,
        "_execute_workflow_impl",
        AsyncMock(
            return_value={
                "agent_status": _full_status(),
                "execution_metadata": {},
                "report": {"title": "report"},
            }
        ),
    )

    await analysis._execute_workflow("clean-run", request)

    assert analysis.workflows["clean-run"]["status"] == "completed"
    analysis.workflows.pop("clean-run", None)


def test_partial_runs_are_evictable_terminal_entries() -> None:
    """Partial entries hold heavy finished results — evictable like completed."""
    from datetime import datetime

    from app.utils.bounded_store import evict_oldest_terminal

    mixed = {
        "partial-new": {"status": "partial", "completed_at": datetime(2026, 1, 2)},
        "completed-old": {"status": "completed", "completed_at": datetime(2025, 1, 1)},
    }
    evicted = evict_oldest_terminal(
        mixed,
        2,
        terminal_statuses=("completed", "failed", "partial"),
        timestamp_of=lambda e: e.get("completed_at") or datetime.min,
    )
    assert evicted == "completed-old"  # oldest terminal goes first
    assert "completed-old" not in mixed and "partial-new" in mixed

    all_partial = {
        "a": {"status": "partial", "completed_at": datetime(2026, 1, 1)},
        "b": {"status": "partial", "completed_at": datetime(2026, 1, 2)},
    }
    assert (
        evict_oldest_terminal(
            all_partial,
            2,
            terminal_statuses=("completed", "failed", "partial"),
            timestamp_of=lambda e: e.get("completed_at") or datetime.min,
        )
        == "a"
    )  # a partial entry is itself evictable when it's the oldest terminal
