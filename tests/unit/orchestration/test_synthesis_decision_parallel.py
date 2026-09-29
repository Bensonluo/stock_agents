"""Routing + graph tests for the second fan-out: research_synthesis ∥ decision.

DecisionMakingAgent.process reads only technical/fundamental/sentiment/risk
(plus regime keys extracted from risk) — it never reads research_synthesis,
so after risk_assessment the two branches are data-independent and can run
in the same superstep. Report generation is the true fan-in: it consumes
both ``decision`` and ``research_synthesis``. The synthesis_barrier joins
the two branches with STRICT completion semantics — unlike the analysis
barrier's budget-exhausted "settled" leniency, a branch that actually died
must never release the report.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.orchestration.orchestrator import MultiAgentOrchestrator
from app.orchestration.state import create_initial_state


class _Concurrency:
    """Tracks how many stub agents are in flight at once."""

    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    async def hold(self, delay: float) -> None:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(delay)
        finally:
            self.active -= 1


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


class SpyProcessAgent:
    """StatelessAgent-style stub: snapshot of agent_status per call."""

    def __init__(
        self,
        value: Any,
        fail_first: int = 0,
        tracker: _Concurrency | None = None,
        delay: float = 0.0,
    ) -> None:
        self.value = value
        self.fail_first = fail_first
        self.tracker = tracker
        self.delay = delay
        self.attempts = 0
        self.calls: list[dict[str, str]] = []

    async def process(self, state: dict) -> Any:
        self.calls.append(dict(state.get("agent_status", {})))
        self.attempts += 1
        if self.tracker:
            await self.tracker.hold(self.delay)
        if self.attempts <= self.fail_first:
            raise RuntimeError(f"transient failure #{self.attempts}")
        return self.value


def _build_orchestrator(
    synthesis: SpyProcessAgent | None = None,
    decision: SpyProcessAgent | None = None,
    tracker: _Concurrency | None = None,
) -> MultiAgentOrchestrator:
    """Real graph + wiring, stubbed agents (no network, no LLM)."""
    orch = MultiAgentOrchestrator(llm=None)
    orch.data_agent = StubRunAgent("market_data", {"TEST": {"current_price": 100.0}})
    orch.technical_agent = StubRunAgent("technical_analysis", {"TEST": {"rsi": 55}})
    orch.fundamental_agent = StubRunAgent("fundamental_analysis", {"TEST": {"pe_ratio": 19.0}})
    orch.sentiment_agent = SpyProcessAgent({"TEST": {"sentiment": "neutral"}})
    orch.risk_agent = SpyProcessAgent({"risk_by_symbol": {"TEST": {"beta": 1.1}}})
    orch.synthesis_agent = synthesis or SpyProcessAgent(
        {"audit": {"verdict": "pass"}}, tracker=tracker, delay=0.08
    )
    orch.decision_agent = decision or SpyProcessAgent(
        {"decisions": {"TEST": {"action": "hold"}}}, tracker=tracker, delay=0.08
    )
    orch.report_agent = SpyProcessAgent({"sections": {"overview": "ok"}})
    return orch


def _invoke(orch: MultiAgentOrchestrator, **state_kwargs) -> dict:
    state = create_initial_state(query="Analyze TEST", symbols=["TEST"], **state_kwargs)
    return asyncio.run(orch.graph.ainvoke(state))


def _state(
    agent_status: dict[str, str],
    retry_count: dict[str, int] | None = None,
    parallel: bool = True,
) -> dict:
    return {
        "agent_status": agent_status,
        "retry_count": retry_count or {},
        "max_retries": 3,
        "parallel_execution": parallel,
    }


_ORCH = MultiAgentOrchestrator(llm=None)


# ---------------------------------------------------------------------------
# Routing unit tests
# ---------------------------------------------------------------------------


class TestRouteAfterRisk:
    def test_parallel_mode_fans_out_synthesis_and_decision(self) -> None:
        routed = _ORCH._route_after_risk(_state({"risk_assessment": "completed"}))
        assert routed == ["fan_out_synthesis", "fan_out_decision"]

    def test_sequential_mode_keeps_the_serial_chain(self) -> None:
        routed = _ORCH._route_after_risk(_state({"risk_assessment": "completed"}, parallel=False))
        assert routed == "sequential"

    def test_failed_with_budget_routes_to_retry(self) -> None:
        routed = _ORCH._route_after_risk(
            _state({"risk_assessment": "failed"}, retry_count={"risk_assessment": 1})
        )
        assert routed == "retry"

    def test_failed_without_budget_routes_to_error(self) -> None:
        routed = _ORCH._route_after_risk(
            _state({"risk_assessment": "failed"}, retry_count={"risk_assessment": 3})
        )
        assert routed == "error"


class TestRouteAfterSynthesis:
    def test_parallel_mode_joins_report(self) -> None:
        routed = _ORCH._route_after_synthesis(_state({"research_synthesis": "completed"}))
        assert routed == "join_report"

    def test_sequential_mode_chains_to_decision(self) -> None:
        routed = _ORCH._route_after_synthesis(
            _state({"research_synthesis": "completed"}, parallel=False)
        )
        assert routed == "decision"

    def test_retry_and_error_unchanged(self) -> None:
        assert (
            _ORCH._route_after_synthesis(
                _state({"research_synthesis": "failed"}, retry_count={"research_synthesis": 1})
            )
            == "retry"
        )
        assert (
            _ORCH._route_after_synthesis(
                _state({"research_synthesis": "failed"}, retry_count={"research_synthesis": 3})
            )
            == "error"
        )


class TestRouteAfterDecision:
    def test_parallel_mode_joins_report(self) -> None:
        routed = _ORCH._route_after_decision(_state({"decision_making": "completed"}))
        assert routed == "join_report"

    def test_sequential_mode_chains_to_report(self) -> None:
        routed = _ORCH._route_after_decision(
            _state({"decision_making": "completed"}, parallel=False)
        )
        assert routed == "report"

    def test_retry_and_error_unchanged(self) -> None:
        assert (
            _ORCH._route_after_decision(
                _state({"decision_making": "failed"}, retry_count={"decision_making": 1})
            )
            == "retry"
        )
        assert (
            _ORCH._route_after_decision(
                _state({"decision_making": "failed"}, retry_count={"decision_making": 3})
            )
            == "error"
        )


class TestRouteAfterSynthesisBarrier:
    def test_both_completed_releases_report(self) -> None:
        routed = _ORCH._route_after_synthesis_barrier(
            _state({"research_synthesis": "completed", "decision_making": "completed"})
        )
        assert routed == "proceed_report"

    def test_one_running_waits(self) -> None:
        routed = _ORCH._route_after_synthesis_barrier(
            _state({"research_synthesis": "completed", "decision_making": "running"})
        )
        assert routed == "wait"

    def test_one_failed_with_budget_left_waits(self) -> None:
        # Retrying branch: the barrier must spin, not release and not abort.
        routed = _ORCH._route_after_synthesis_barrier(
            _state(
                {"research_synthesis": "failed", "decision_making": "completed"},
                retry_count={"research_synthesis": 1},
            )
        )
        assert routed == "wait"

    def test_one_never_started_waits(self) -> None:
        routed = _ORCH._route_after_synthesis_barrier(_state({"research_synthesis": "completed"}))
        assert routed == "wait"

    def test_exhausted_branch_never_releases_report(self) -> None:
        # Strict join: a dead branch must not produce a report run.
        routed = _ORCH._route_after_synthesis_barrier(
            _state(
                {"research_synthesis": "failed", "decision_making": "completed"},
                retry_count={"research_synthesis": 3},
            )
        )
        assert routed != "proceed_report"


# ---------------------------------------------------------------------------
# Graph-level tests
# ---------------------------------------------------------------------------


def test_synthesis_and_decision_run_concurrently() -> None:
    tracker = _Concurrency()
    orch = _build_orchestrator(tracker=tracker)

    result = _invoke(orch, thread_id="t-fanout2-parallel")

    # The two post-risk branches were in flight at the same time.
    assert tracker.max_active >= 2, f"expected overlap, max_active={tracker.max_active}"
    assert result["errors"] == []
    assert result["agent_status"]["research_synthesis"] == "completed"
    assert result["agent_status"]["decision_making"] == "completed"
    assert result["research_synthesis"]["audit"]["verdict"] == "pass"
    assert result["decision"]["decisions"]["TEST"]["action"] == "hold"
    assert result["report"]["sections"]["overview"] == "ok"
    # Same agent-execution count as the serial tail: the barrier adds none.
    assert result["current_step"] == 8


def test_report_waits_for_both_branches() -> None:
    """Report must observe BOTH synthesis and decision completed."""
    orch = _build_orchestrator()

    result = _invoke(orch, thread_id="t-fanout2-report-inputs")

    report_statuses = orch.report_agent.calls[0]
    assert report_statuses.get("research_synthesis") == "completed"
    assert report_statuses.get("decision_making") == "completed"
    assert len(orch.report_agent.calls) == 1
    assert result["report"]["sections"]["overview"] == "ok"


def test_transient_synthesis_failure_recovers_through_barrier() -> None:
    synthesis = SpyProcessAgent({"audit": {"verdict": "pass"}}, fail_first=2)
    orch = _build_orchestrator(synthesis=synthesis)

    result = _invoke(orch, thread_id="t-fanout2-recover")

    assert synthesis.attempts == 3  # two failures, then recovery
    assert result["agent_status"]["research_synthesis"] == "completed"
    assert len(orch.report_agent.calls) == 1
    assert result["report"]["sections"]["overview"] == "ok"
    # data(1) + 3 analyses + risk(1) + synthesis(3) + decision(1) + report(1).
    assert result["current_step"] == 10


def test_exhausted_synthesis_terminates_without_report() -> None:
    synthesis = SpyProcessAgent({"audit": {"verdict": "pass"}}, fail_first=99)
    orch = _build_orchestrator(synthesis=synthesis)

    result = _invoke(orch, thread_id="t-fanout2-synthesis-dead")

    # The branch exhausted its budget; the run terminates at the error
    # handler instead of spinning the barrier to the recursion limit.
    assert synthesis.attempts == 3
    assert result["agent_status"]["research_synthesis"] == "failed"
    assert result["error_summary"]["errors_by_agent"]["research_synthesis"]
    assert "report" not in result or result.get("report") in (None, {})
    assert len(orch.report_agent.calls) == 0


def test_sequential_mode_preserves_serial_chain() -> None:
    orch = _build_orchestrator()

    result = _invoke(orch, thread_id="t-fanout2-sequential", parallel_execution=False)

    assert result["errors"] == []
    assert result["report"]["sections"]["overview"] == "ok"
    assert result["current_step"] == 8
    # Old chain order: decision ran after synthesis had already completed.
    decision_statuses = orch.decision_agent.calls[0]
    assert decision_statuses.get("research_synthesis") == "completed"


def test_synthesis_barrier_is_not_tracked_as_an_agent() -> None:
    orch = _build_orchestrator()

    result = _invoke(orch, thread_id="t-fanout2-not-agent")

    assert "synthesis_barrier" not in result["agent_status"]
    assert result["current_step"] == 8  # barrier spins add no node executions
