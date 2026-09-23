"""Bound on the API-layer workflow result cache (analysis.workflows)."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.api.routes import analysis

pytestmark = pytest.mark.asyncio


def _seed(cap: int) -> None:
    analysis.workflows.clear()
    base = datetime.now() - timedelta(hours=2)
    for i in range(cap):
        analysis.workflows[f"old-{i}"] = {
            "status": "completed",
            "result": {"big": "payload"},
            "started_at": base + timedelta(minutes=i),
            "completed_at": base + timedelta(minutes=i),
        }


class TestWorkflowResultCacheBound:
    async def test_store_caps_at_max_tracked(self):
        _seed(analysis.MAX_TRACKED_API_WORKFLOWS)
        analysis._store_workflow("fresh", {"status": "running", "started_at": datetime.now()})
        assert len(analysis.workflows) == analysis.MAX_TRACKED_API_WORKFLOWS
        assert "fresh" in analysis.workflows
        assert "old-0" not in analysis.workflows  # oldest terminal evicted

    async def test_running_entries_survive_while_terminals_exist(self):
        _seed(analysis.MAX_TRACKED_API_WORKFLOWS - 1)
        analysis.workflows["live-runner"] = {"status": "running", "started_at": datetime.now()}
        analysis._store_workflow("fresh", {"status": "running", "started_at": datetime.now()})
        assert "live-runner" in analysis.workflows

    async def test_background_completion_survives_evicted_entry(self, monkeypatch):
        # entry dropped mid-run (cache pressure): write-back must not KeyError
        analysis.workflows.pop("evicted-thread", None)
        monkeypatch.setattr(
            analysis,
            "_execute_workflow_impl",
            AsyncMock(return_value={"agent_status": {}, "execution_metadata": {}}),
        )
        request = analysis.StockAnalysisRequest(query="analyze", symbols=["AAPL"])

        await analysis._execute_workflow("evicted-thread", request)  # no raise

        assert "evicted-thread" not in analysis.workflows
