"""Per-agent timing breakdown carried through graph state into results.

The node wrapper always computed each agent's duration but dropped it
from the state delta — durations lived only in monitor events, so API
responses and history records carried a total execution_time with no
per-agent breakdown. The agent_timings channel (merge_dicts reducer)
accumulates last-attempt durations across the parallel analysis
superstep without clobbering, and execute_workflow copies it into
execution_metadata before serialization and persistence.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.monitoring.workflow_status import PIPELINE_AGENTS
from app.orchestration.orchestrator import MultiAgentOrchestrator
from app.orchestration.state import create_initial_state


class StubRunAgent:
    """BaseAgent-style stub: run() returns a partial state update."""

    def __init__(self, key: str, value: Any, fail_first: int = 0, fail_delay: float = 0.0) -> None:
        self.key = key
        self.value = value
        self.fail_first = fail_first
        self.fail_delay = fail_delay
        self.attempts = 0

    async def run(self, state: dict) -> dict:
        self.attempts += 1
        if self.attempts <= self.fail_first:
            if self.fail_delay:
                await asyncio.sleep(self.fail_delay)
            raise RuntimeError(f"transient failure #{self.attempts}")
        return {self.key: self.value}


class CountingSpyAgent:
    """StatelessAgent-style stub: process() returns the node's state-key value."""

    def __init__(self, value: Any) -> None:
        self.value = value
        self.attempts = 0

    async def process(self, state: dict) -> Any:
        self.attempts += 1
        return self.value


def _build_orchestrator(technical: StubRunAgent | None = None):
    """Real graph + wiring, stubbed agents (no network, no LLM)."""
    orch = MultiAgentOrchestrator(llm=None)
    orch.data_agent = StubRunAgent("market_data", {"TEST": {"current_price": 100.0}})
    orch.technical_agent = technical or StubRunAgent("technical_analysis", {"TEST": {"rsi": 55}})
    orch.fundamental_agent = StubRunAgent("fundamental_analysis", {"TEST": {"pe_ratio": 19.0}})
    orch.sentiment_agent = CountingSpyAgent({"TEST": {"sentiment": "neutral"}})
    orch.risk_agent = CountingSpyAgent({"risk_by_symbol": {"TEST": {"beta": 1.1}}})
    orch.synthesis_agent = CountingSpyAgent({"audit": {"verdict": "pass"}})
    orch.decision_agent = CountingSpyAgent({"decisions": {"TEST": {"action": "hold"}}})
    orch.report_agent = CountingSpyAgent({"sections": {"overview": "ok"}})
    return orch


def _invoke(orch: MultiAgentOrchestrator, **state_kwargs) -> dict:
    state = create_initial_state(query="Analyze TEST", symbols=["TEST"], **state_kwargs)
    return asyncio.run(orch.graph.ainvoke(state))


def test_initial_state_has_empty_timings() -> None:
    """The channel exists in the schema with a clean empty-dict default."""
    state = create_initial_state(query="q", symbols=["TEST"])
    assert state["agent_timings"] == {}


def test_every_pipeline_agent_records_timing() -> None:
    """Default (parallel) run: all 8 pipeline agents present, non-negative floats."""
    final = _invoke(_build_orchestrator())
    timings = final.get("agent_timings")
    assert timings is not None, "agent_timings channel missing from final state"
    assert set(timings) == set(PIPELINE_AGENTS)
    assert all(isinstance(v, float) and v >= 0.0 for v in timings.values())


def test_retry_records_last_attempt_not_failed_attempts() -> None:
    """Two slow failures then a fast success: the stored duration is the
    successful attempt's, not a failed attempt's (last-attempt semantics)."""
    technical = StubRunAgent(
        "technical_analysis", {"TEST": {"rsi": 55}}, fail_first=2, fail_delay=0.05
    )
    final = _invoke(_build_orchestrator(technical=technical))
    assert technical.attempts == 3
    timings = final.get("agent_timings") or {}
    assert set(timings) == set(PIPELINE_AGENTS), "retries must not lose other agents' timings"
    assert 0.0 <= timings["technical_analysis"] < 0.05


def test_execute_workflow_copies_timings_into_execution_metadata(monkeypatch) -> None:
    """execute_workflow exposes the breakdown via execution_metadata, which is
    what API responses and history records actually persist."""
    orch = _build_orchestrator()

    class _StubDB:
        def create_record(self, record) -> None:
            pass

        def update_status(self, **kwargs) -> None:
            pass

    monkeypatch.setattr("app.orchestration.orchestrator.get_database", lambda: _StubDB())
    result = asyncio.run(orch.execute_workflow(query="Analyze TEST", symbols=["TEST"]))

    meta = result["execution_metadata"]
    assert meta["execution_time"] > 0
    assert set(meta["agent_timings"]) == set(PIPELINE_AGENTS)
    assert all(isinstance(v, float) for v in meta["agent_timings"].values())
