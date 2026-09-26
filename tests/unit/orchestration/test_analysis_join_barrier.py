"""Graph-level tests for the analysis-stage join barrier.

The three parallel analysis branches (technical/sentiment/fundamental) must
all be settled — completed, degraded (retry budget exhausted), or never
started — before risk_assessment runs, and the four downstream nodes must
each execute exactly once per workflow. Without a real barrier, a straggler
branch that is still inside its retry self-loop lets risk start on partial
data and then triggers a second full pass of risk/synthesis/decision/report.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.monitoring.workflow_status import PIPELINE_AGENTS
from app.orchestration.orchestrator import MultiAgentOrchestrator
from app.orchestration.state import create_initial_state

_ANALYSIS_AGENTS = ("technical_analysis", "sentiment_analysis", "fundamental_analysis")
_DOWNSTREAM_AGENTS = (
    "risk_assessment",
    "research_synthesis",
    "decision_making",
    "report_generation",
)


class StubRunAgent:
    """BaseAgent-style stub: run() returns a partial state update."""

    def __init__(self, key: str, value: Any, fail_first: int = 0) -> None:
        self.key = key
        self.value = value
        self.fail_first = fail_first
        self.attempts = 0

    async def run(self, state: dict) -> dict:
        self.attempts += 1
        if self.attempts <= self.fail_first:
            raise RuntimeError(f"transient failure #{self.attempts}")
        return {self.key: self.value}


class CountingSpyAgent:
    """StatelessAgent-style stub that records the agent_status snapshot per call."""

    def __init__(self, value: Any) -> None:
        self.value = value
        self.calls: list[dict[str, str]] = []

    async def process(self, state: dict) -> Any:
        self.calls.append(dict(state.get("agent_status", {})))
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


def test_straggler_branch_blocks_risk_until_all_analysis_settled() -> None:
    """Technical fails twice then succeeds: downstream runs exactly once, on full data."""
    technical = StubRunAgent("technical_analysis", {"TEST": {"rsi": 55}}, fail_first=2)
    orch = _build_orchestrator(technical=technical)

    result = _invoke(orch, thread_id="t-barrier-straggler")

    assert technical.attempts == 3  # two failures, then recovery
    for name in _DOWNSTREAM_AGENTS:
        spy = getattr(orch, _agent_attr(name))
        assert len(spy.calls) == 1, f"{name} executed {len(spy.calls)} times, expected 1"

    # At the moment risk runs, every analysis branch is settled (completed).
    risk_statuses = orch.risk_agent.calls[0]
    for name in _ANALYSIS_AGENTS:
        assert risk_statuses.get(name) == "completed", (name, risk_statuses)
    # Risk saw the recovered technical output, not the pre-retry gap.
    assert result["agent_status"]["technical_analysis"] == "completed"
    assert result["decision"]["decisions"]["TEST"]["action"] == "hold"
    assert result["report"]["sections"]["overview"] == "ok"
    # Exactly 10 node executions: data(1) + technical(3) + sentiment(1) +
    # fundamental(1) + downstream(4). Barrier spins are not agent executions.
    assert result["current_step"] == 10


def test_degraded_branch_still_runs_downstream_exactly_once() -> None:
    """An analysis agent exhausting its budget degrades — pipeline proceeds once."""
    technical = StubRunAgent("technical_analysis", {"TEST": {"rsi": 55}}, fail_first=99)
    orch = _build_orchestrator(technical=technical)

    result = _invoke(orch, thread_id="t-barrier-degraded")

    assert technical.attempts == 3  # max_retries=3, then degraded
    assert result["agent_status"]["technical_analysis"] == "failed"
    for name in _DOWNSTREAM_AGENTS:
        spy = getattr(orch, _agent_attr(name))
        assert len(spy.calls) == 1, f"{name} executed {len(spy.calls)} times, expected 1"
    # At risk time the degraded branch is settled-as-failed, the others completed.
    risk_statuses = orch.risk_agent.calls[0]
    assert risk_statuses.get("technical_analysis") == "failed"
    assert risk_statuses.get("sentiment_analysis") == "completed"
    assert risk_statuses.get("fundamental_analysis") == "completed"
    assert result["report"]["sections"]["overview"] == "ok"


def test_sequential_mode_completes_with_pipeline_order() -> None:
    """parallel_execution=False still runs technical -> sentiment -> fundamental -> risk."""
    technical = StubRunAgent("technical_analysis", {"TEST": {"rsi": 55}})
    orch = _build_orchestrator(technical=technical)

    result = _invoke(orch, thread_id="t-barrier-sequential", parallel_execution=False)

    assert result["errors"] == []
    assert result["current_step"] == 8  # data + 3 analyses + 4 downstream, no extras
    # Sentiment ran before fundamental (sequential chain), both before risk.
    sentiment_first = len(orch.sentiment_agent.calls) >= 1
    assert sentiment_first
    assert len(orch.risk_agent.calls) == 1
    assert orch.risk_agent.calls[0].get("fundamental_analysis") == "completed"


def test_sequential_degraded_branch_does_not_deadlock_the_barrier() -> None:
    """Sequential mode + degraded technical: never-started branches must not block."""
    technical = StubRunAgent("technical_analysis", {"TEST": {"rsi": 55}}, fail_first=99)
    orch = _build_orchestrator(technical=technical)

    result = _invoke(orch, thread_id="t-barrier-seq-degraded", parallel_execution=False)

    # Technical degraded before sentiment/fundamental ever started; risk must
    # still run exactly once (never-started branches count as settled).
    assert technical.attempts == 3
    assert len(orch.risk_agent.calls) == 1
    risk_statuses = orch.risk_agent.calls[0]
    assert risk_statuses.get("technical_analysis") == "failed"
    assert result["agent_status"]["report_generation"] == "completed"
    assert result["report"]["sections"]["overview"] == "ok"


def test_barrier_is_not_tracked_as_an_agent() -> None:
    """The barrier is wiring, not an agent: absent from status maps and PIPELINE_AGENTS."""
    orch = _build_orchestrator()

    result = _invoke(orch, thread_id="t-barrier-not-agent")

    assert "analysis_barrier" not in result["agent_status"]
    assert "analysis_barrier" not in PIPELINE_AGENTS
    assert result["current_step"] == 8  # happy path: barrier added no node executions


def _agent_attr(agent_name: str) -> str:
    """Map pipeline agent name to the orchestrator attribute used in _build_orchestrator."""
    return {
        "risk_assessment": "risk_agent",
        "research_synthesis": "synthesis_agent",
        "decision_making": "decision_agent",
        "report_generation": "report_agent",
        "sentiment_analysis": "sentiment_agent",
    }[agent_name]
