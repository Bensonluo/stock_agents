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
