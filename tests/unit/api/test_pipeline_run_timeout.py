"""Pipeline overall run wall-clock bound (iteration 178).

Every node is bounded (BaseAgent.run for run-mode agents, iteration-173
wait_for for process-mode agents), but the worst-case bounded pipeline is
8 nodes x 300s x retry attempts — tens of minutes holding one of the two
analysis-capacity slots. The ReAct path got its overall bound in
iteration 177; this is the pipeline twin.
"""

import asyncio
from pathlib import Path

import pytest

import app.api.routes.analysis as analysis
from app.config import Settings, settings

pytestmark = pytest.mark.asyncio


class _StubOrchestrator:
    """Orchestrator stub. `hang=True` simulates a workflow that never
    returns — the unbounded failure mode the run budget must fence."""

    def __init__(self, hang: bool = False, delay: float = 0.0):
        self._hang = hang
        self._delay = delay

    async def execute_workflow(self, **kwargs) -> dict:
        if self._hang:
            await asyncio.sleep(30)  # "forever" for test purposes
            return {}
        await asyncio.sleep(self._delay)
        return {
            "errors": [],
            "agent_status": {},
            "current_step": 1,
            "current_agent": None,
        }


def _wire(monkeypatch, hang: bool = False, delay: float = 0.0) -> None:
    monkeypatch.setattr(
        analysis, "get_orchestrator", lambda: _StubOrchestrator(hang=hang, delay=delay)
    )


async def _run_impl_with_antihang_guard() -> dict | None:
    """Outer 15s bound so the RED phase fails fast instead of hanging the
    suite (iteration-173/175/177 pattern)."""
    try:
        return await asyncio.wait_for(
            analysis._execute_workflow_impl(
                thread_id="workflow-t-test",
                query="q",
                symbols=["AAPL"],
                max_retries=1,
                timeout_per_agent=5,
                parallel_execution=True,
            ),
            15,
        )
    except TimeoutError as e:
        raise AssertionError(
            "outer antihang guard tripped — the run bound did not fence the hung workflow"
        ) from e


class TestHungWorkflowIsBounded:
    async def test_run_timeout_kills_hung_workflow_with_named_error(self, monkeypatch):
        monkeypatch.setattr(settings, "pipeline_run_timeout", 0.05)
        _wire(monkeypatch, hang=True)

        with pytest.raises(RuntimeError) as exc_info:
            await _run_impl_with_antihang_guard()

        # Names the knob and the budget so the operator knows where to look;
        # flows into the existing failure path (workflow marked failed, slot
        # released by the guarded wrapper's finally).
        assert "pipeline_run_timeout" in str(exc_info.value)
        assert "0.05" in str(exc_info.value)


class TestDisableAndSuccess:
    async def test_zero_disables_the_bound(self, monkeypatch):
        monkeypatch.setattr(settings, "pipeline_run_timeout", 0)
        _wire(monkeypatch, delay=0.05)

        result = await _run_impl_with_antihang_guard()

        assert result is not None
        assert result["current_step"] == 1

    async def test_default_budget_harmless_to_fast_workflows(self, monkeypatch):
        _wire(monkeypatch, delay=0.01)

        result = await _run_impl_with_antihang_guard()

        assert result is not None
        assert result["current_step"] == 1


class TestWiring:
    async def test_default_is_1800_and_documented(self):
        assert Settings.model_fields["pipeline_run_timeout"].default == 1800.0

        env_example = (Path(__file__).parents[3] / ".env.example").read_text()
        assert "PIPELINE_RUN_TIMEOUT" in env_example
