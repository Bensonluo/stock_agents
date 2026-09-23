"""Graph-level tests for the parallel fan-out analysis stage.

Covers the LangGraph map-reduce topology: nodes return partial updates,
reducers accumulate shared channels, the three analysis agents run in the
same superstep, retries are budgeted by retry_count, and an analysis agent
that exhausts its budget degrades gracefully instead of dead-ending the
workflow.
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

    def __init__(
        self,
        key: str,
        value: Any,
        tracker: _Concurrency | None = None,
        delay: float = 0.0,
        fail_first: int = 0,
    ) -> None:
        self.key = key
        self.value = value
        self.tracker = tracker
        self.delay = delay
        self.fail_first = fail_first
        self.attempts = 0

    async def run(self, state: dict) -> dict:
        self.attempts += 1
        if self.tracker:
            await self.tracker.hold(self.delay)
        elif self.delay:
            await asyncio.sleep(self.delay)
        if self.attempts <= self.fail_first:
            raise RuntimeError(f"transient failure #{self.attempts}")
        return {self.key: self.value}


class StubProcessAgent:
    """StatelessAgent-style stub: process() returns the node's state value."""

    def __init__(self, value: Any, delay: float = 0.0) -> None:
        self.value = value
        self.delay = delay

    async def process(self, state: dict) -> Any:
        await asyncio.sleep(self.delay)
        return self.value


def _build_orchestrator(
    tracker: _Concurrency | None = None,
    technical: StubRunAgent | None = None,
    data: StubRunAgent | None = None,
) -> MultiAgentOrchestrator:
    """Real graph + graph wiring, stubbed agents (no network, no LLM)."""
    orch = MultiAgentOrchestrator(llm=None)
    orch.data_agent = data or StubRunAgent(
        "market_data", {"TEST": {"current_price": 100.0}}, delay=0.0
    )
    orch.technical_agent = technical or StubRunAgent(
        "technical_analysis", {"TEST": {"rsi": 55}}, tracker=tracker, delay=0.08
    )
    orch.fundamental_agent = StubRunAgent(
        "fundamental_analysis", {"TEST": {"pe_ratio": 19.0}}, tracker=tracker, delay=0.08
    )
    orch.sentiment_agent = StubProcessAgent({"TEST": {"sentiment": "neutral"}}, delay=0.08)
    orch.risk_agent = StubProcessAgent({"risk_by_symbol": {"TEST": {"beta": 1.1}}})
    orch.synthesis_agent = StubProcessAgent({"audit": {"verdict": "pass"}})
    orch.decision_agent = StubProcessAgent({"decisions": {"TEST": {"action": "hold"}}})
    orch.report_agent = StubProcessAgent({"sections": {"overview": "ok"}})
    return orch


_ALL_AGENTS = (
    "data_collection",
    "technical_analysis",
    "sentiment_analysis",
    "fundamental_analysis",
    "risk_assessment",
    "research_synthesis",
    "decision_making",
    "report_generation",
)


def _invoke(orch: MultiAgentOrchestrator, **state_kwargs) -> dict:
    state = create_initial_state(query="Analyze TEST", symbols=["TEST"], **state_kwargs)
    return asyncio.run(orch.graph.ainvoke(state))


def test_parallel_stage_runs_analysis_agents_concurrently() -> None:
    tracker = _Concurrency()
    orch = _build_orchestrator(tracker=tracker)

    result = _invoke(orch, thread_id="t-parallel")

    # The three analysis agents were in flight at the same time.
    assert tracker.max_active >= 2, f"expected concurrent analysis, max_active={tracker.max_active}"

    assert result["errors"] == []
    assert result["agent_status"] == {name: "completed" for name in _ALL_AGENTS}
    assert result["technical_analysis"] == {"TEST": {"rsi": 55}}
    assert result["sentiment_analysis"] == {"TEST": {"sentiment": "neutral"}}
    assert result["fundamental_analysis"] == {"TEST": {"pe_ratio": 19.0}}
    assert result["decision"]["decisions"]["TEST"]["action"] == "hold"
    assert result["report"]["sections"]["overview"] == "ok"
    # +1 per node execution: data + 3 parallel analyses + 4 downstream nodes.
    assert result["current_step"] == 8


def test_sequential_mode_runs_analysis_agents_one_at_a_time() -> None:
    tracker = _Concurrency()
    orch = _build_orchestrator(tracker=tracker)

    result = _invoke(orch, thread_id="t-sequential", parallel_execution=False)

    assert tracker.max_active == 1
    assert result["errors"] == []
    assert result["agent_status"] == {name: "completed" for name in _ALL_AGENTS}
    assert result["current_step"] == 8


def test_transient_failure_recovers_instead_of_retry_looping() -> None:
    # Regression: routing on cumulative errors made a recovered agent retry
    # forever, because success never drained the retry budget.
    technical = StubRunAgent("technical_analysis", {"TEST": {"rsi": 55}}, fail_first=2)
    orch = _build_orchestrator(technical=technical)

    result = _invoke(orch, thread_id="t-recover")

    assert technical.attempts == 3  # two failures, then success sticks
    assert result["agent_status"]["technical_analysis"] == "completed"
    tech_errors = [e for e in result["errors"] if e["agent"] == "technical_analysis"]
    assert len(tech_errors) == 2  # no duplicated entries from echoed lists
    assert result["decision"]["decisions"]["TEST"]["action"] == "hold"


def test_exhausted_analysis_agent_degrades_gracefully() -> None:
    technical = StubRunAgent("technical_analysis", {"TEST": {"rsi": 55}}, fail_first=99)
    orch = _build_orchestrator(technical=technical)

    result = _invoke(orch, thread_id="t-degraded")

    # max_retries=3 -> three failed attempts, then the degraded edge fires.
    assert technical.attempts == 3
    assert result["agent_status"]["technical_analysis"] == "failed"
    assert result["retry_count"]["technical_analysis"] == 3
    # The pipeline still produces a decision/report from the other analyses.
    for name in _ALL_AGENTS:
        if name != "technical_analysis":
            assert result["agent_status"][name] == "completed", name
    assert result["decision"]["decisions"]["TEST"]["action"] == "hold"
    assert result["report"]["sections"]["overview"] == "ok"


def test_data_collection_failure_routes_to_error_handler() -> None:
    data = StubRunAgent("market_data", {}, fail_first=99)
    orch = _build_orchestrator(data=data)

    result = _invoke(orch, thread_id="t-data-error")

    assert result["agent_status"]["data_collection"] == "failed"
    assert result["error_summary"]["total_errors"] == 3
    assert result["execution_metadata"]["had_errors"] is True
    assert "report" not in result or result.get("report") in (None, {})


def test_agent_events_carry_running_agents_metadata() -> None:
    """agent_start/agent_success broadcasts include the fan-out running set."""
    from app.monitoring import get_monitor, workflow_status

    events: list[dict] = []

    class _FakeBroadcast:
        async def broadcast_agent_event(self, **kwargs) -> None:
            events.append(kwargs)

        async def broadcast_workflow_complete(self, **kwargs) -> None:
            pass

    monitor = get_monitor()
    original_bm = monitor.broadcast_manager
    monitor.broadcast_manager = _FakeBroadcast()
    workflow_status.reset()
    try:
        orch = _build_orchestrator()
        result = _invoke(orch, thread_id="t-broadcast")
        assert result["agent_status"]["report_generation"] == "completed"

        starts = [e for e in events if e.get("event_type") == "agent_start"]
        parallel = [
            e
            for e in starts
            if e["agent_name"]
            in ("technical_analysis", "sentiment_analysis", "fundamental_analysis")
        ]
        assert parallel, "no analysis agent_start events captured"

        # every analysis start carries the running set including itself
        for e in parallel:
            assert e["agent_name"] in e["metadata"]["running_agents"]

        # the staggered starts must observe the fan-out: at least one event
        # sees another analysis agent already in flight
        assert any(len(e["metadata"]["running_agents"]) >= 2 for e in parallel), [
            e["metadata"]["running_agents"] for e in parallel
        ]

        # success events carry the post-completion snapshot (list field present)
        successes = [e for e in events if e.get("event_type") == "agent_success"]
        assert successes and all("running_agents" in e["metadata"] for e in successes)
    finally:
        monitor.broadcast_manager = original_bm
        workflow_status.reset()
