"""Tests for the extracted in-memory workflow status store."""

import pytest

from app.monitoring import workflow_status

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _clean_store():
    workflow_status.reset()
    yield
    workflow_status.reset()


class TestWorkflowStatusStore:
    async def test_init_registers_all_pipeline_agents(self):
        workflow_status.init_workflow("t1")
        state = workflow_status.get_workflow_state("t1")
        assert "research_synthesis" in state["agents"]  # was missing pre-extraction
        assert state["status"] == "pending"
        assert state["progress"] == 0.0
        assert workflow_status.get_logs("t1") == []

    async def test_update_agent_status_lifecycle(self):
        workflow_status.init_workflow("t1")
        workflow_status.update_agent_status("t1", "data_collection", "running")
        state = workflow_status.get_workflow_state("t1")
        assert state["status"] == "running"
        assert state["current_agent"] == "data_collection"
        assert state["agents"]["data_collection"]["started_at"] is not None

        workflow_status.update_agent_status("t1", "data_collection", "completed")
        state = workflow_status.get_workflow_state("t1")
        assert state["agents"]["data_collection"]["completed_at"] is not None
        assert state["agents"]["data_collection"]["started_at"] is not None  # preserved

    async def test_unknown_thread_auto_inits(self):
        workflow_status.update_agent_status("fresh", "risk_assessment", "running")
        state = workflow_status.get_workflow_state("fresh")
        assert state is not None
        assert state["agents"]["risk_assessment"]["status"] == "running"

    async def test_failure_marks_workflow_failed(self):
        workflow_status.init_workflow("t1")
        workflow_status.update_agent_status("t1", "technical_analysis", "failed", error="boom")
        state = workflow_status.get_workflow_state("t1")
        assert state["status"] == "failed"
        assert state["agents"]["technical_analysis"]["error"] == "boom"

    async def test_all_completed_reaches_100_percent(self):
        workflow_status.init_workflow("t1")
        for agent in workflow_status.PIPELINE_AGENTS:
            workflow_status.update_agent_status("t1", agent, "completed")
        state = workflow_status.get_workflow_state("t1")
        assert state["status"] == "completed"
        assert state["progress"] == 100.0

    async def test_log_retention_cap(self):
        workflow_status.init_workflow("t1")
        for i in range(workflow_status.MAX_LOG_ENTRIES + 25):
            workflow_status.add_log("t1", "system", "info", f"entry {i}")
        assert len(workflow_status.get_logs("t1", limit=10_000)) == workflow_status.MAX_LOG_ENTRIES

    async def test_list_workflows_and_get_missing(self):
        workflow_status.init_workflow("t1")
        summaries = workflow_status.list_workflows()
        assert [s["thread_id"] for s in summaries] == ["t1"]
        assert workflow_status.get_workflow_state("ghost") is None


class TestMonitorRouteDelegates:
    """The monitor API routes read the same shared store."""

    async def test_route_module_reexports_helpers(self):
        from app.api.routes import monitor as monitor_route

        assert monitor_route.init_workflow is workflow_status.init_workflow
        assert monitor_route.update_agent_status is workflow_status.update_agent_status
        assert monitor_route.add_log is workflow_status.add_log

    async def test_orchestrator_no_longer_imports_api_layer(self):
        """The layering fix: orchestration must not import from app.api.*"""
        import app.orchestration.orchestrator as orch_module

        source = open(orch_module.__file__).read()
        assert "app.api.routes" not in source


class TestCloseOrchestrator:
    async def test_closes_sqlite_checkpoint_manager(self, tmp_path, monkeypatch):
        from app.api import dependencies
        from app.orchestration import SqliteCheckpointManager

        manager = SqliteCheckpointManager(db_path=str(tmp_path / "ck.db"))
        closed = []

        async def _aclose():
            closed.append(True)

        monkeypatch.setattr(manager, "aclose", _aclose)
        orch = dependencies.MultiAgentOrchestrator(llm=None, checkpoint_manager=manager)
        dependencies._orchestrator = orch

        await dependencies.close_orchestrator()

        assert closed == [True]
        assert dependencies._orchestrator is None

    async def test_close_with_no_orchestrator_is_noop(self):
        from app.api import dependencies

        dependencies._orchestrator = None
        await dependencies.close_orchestrator()  # must not raise
