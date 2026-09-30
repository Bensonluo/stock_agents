"""ReAct overall run wall-clock bound (iteration 177).

Iterations are capped (agent_max_iterations=15), every tool call is bounded
(react_tool_timeout, iteration 175) and the LLM client carries 90s — but the
worst-case bounded run is still 15 x (90s LLM + k x 120s tools): tens of
minutes holding one of the two analysis-capacity slots (iteration 170).
The bound marks the run failed through the existing degradation path and
the guarded wrapper's finally releases the slot.
"""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import app.api.routes.agent as agent
from app.config import Settings, settings

pytestmark = pytest.mark.asyncio


class _StubAgent:
    """ReActAgent stub. `hang=True` simulates an analyze() that never
    returns — the unbounded failure mode the run budget must fence."""

    def __init__(self, hang: bool = False, delay: float = 0.0):
        self._hang = hang
        self._delay = delay

    async def analyze(self, **kwargs) -> dict:
        if self._hang:
            await asyncio.sleep(30)  # "forever" for test purposes
            return {}
        await asyncio.sleep(self._delay)
        return {
            "answer": "ok",
            "report": None,
            "iterations": 3,
            "tools_used": [],
            "cost": 0.0,
        }


def _wire(monkeypatch, hang: bool = False, delay: float = 0.0) -> None:
    monkeypatch.setattr(agent, "ReActAgent", lambda: _StubAgent(hang=hang, delay=delay))
    # Skip real SQLite writes; the module dicts assert the outcome instead.
    monkeypatch.setattr(agent, "_save_to_db", MagicMock())


async def _run_with_antihang_guard(thread_id: str) -> None:
    """Outer 15s bound so the RED phase fails fast instead of hanging the
    suite (iteration-173/175 pattern)."""
    await asyncio.wait_for(
        agent._run_analysis(thread_id=thread_id, query="q", symbols=["AAPL"], max_iterations=15),
        15,
    )


class TestHungRunIsBounded:
    async def test_run_timeout_kills_hung_analyze_and_fails_cleanly(self, monkeypatch):
        monkeypatch.setattr(settings, "react_run_timeout", 0.05)
        _wire(monkeypatch, hang=True)

        await _run_with_antihang_guard("react-t-timeout")

        progress = agent._progress_states["react-t-timeout"]
        assert progress["status"] == "failed"
        assert progress["current_step"] == "failed"
        assert progress["completed_at"] is not None
        assert "timed out" in agent._results["react-t-timeout"]["answer"]
        # Names the knob and the budget so the operator knows where to look.
        assert "react_run_timeout" in agent._results["react-t-timeout"]["answer"]
        assert "0.05" in agent._results["react-t-timeout"]["answer"]


class TestDisableAndSuccess:
    async def test_zero_disables_the_bound(self, monkeypatch):
        monkeypatch.setattr(settings, "react_run_timeout", 0)
        _wire(monkeypatch, delay=0.05)

        await _run_with_antihang_guard("react-t-disabled")

        assert agent._progress_states["react-t-disabled"]["status"] == "completed"
        assert agent._results["react-t-disabled"]["answer"] == "ok"

    async def test_default_budget_harmless_to_fast_runs(self, monkeypatch):
        _wire(monkeypatch, delay=0.01)

        await _run_with_antihang_guard("react-t-default")

        assert agent._progress_states["react-t-default"]["status"] == "completed"
        assert agent._results["react-t-default"]["answer"] == "ok"


class TestWiring:
    async def test_default_is_900_and_documented(self):
        assert Settings.model_fields["react_run_timeout"].default == 900.0

        env_example = (Path(__file__).parents[3] / ".env.example").read_text()
        assert "REACT_RUN_TIMEOUT" in env_example
