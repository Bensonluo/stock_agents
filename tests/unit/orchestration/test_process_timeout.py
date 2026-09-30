"""Node-level timeout for StatelessAgent.process() calls.

BaseAgent.run() wraps execute() with the TimeLimiter (timeout, circuit
breaker), but the five StatelessAgent pipeline nodes — sentiment, risk,
synthesis, decision, report — are invoked via process() with no bound at
all: a hung process() stalls the pipeline forever and, since iteration
170's concurrency cap, permanently holds an analysis-capacity slot. The
node wrapper now bounds process() with state["timeout_per_agent"]
(<= 0 disables), mirroring what BaseAgent.run() does internally for
run-mode agents.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.orchestration.orchestrator import MultiAgentOrchestrator
from app.orchestration.state import create_initial_state

from tests.unit.orchestration.test_agent_timings import (
    CountingSpyAgent,
    StubRunAgent,
)


class SlowProcessAgent:
    """StatelessAgent-style stub whose process() sleeps before returning."""

    def __init__(self, delay: float, result: Any | None = None) -> None:
        self._delay = delay
        self._result = result if result is not None else {"TEST": {"sentiment": "neutral"}}
        self.attempts = 0

    async def process(self, state: dict) -> Any:
        self.attempts += 1
        await asyncio.sleep(self._delay)
        return self._result


def _build_orchestrator(sentiment: Any | None = None):
    """Real graph + wiring, stubbed agents (no network, no LLM)."""
    orch = MultiAgentOrchestrator(llm=None)
    orch.data_agent = StubRunAgent("market_data", {"TEST": {"current_price": 100.0}})
    orch.technical_agent = StubRunAgent("technical_analysis", {"TEST": {"rsi": 55}})
    orch.fundamental_agent = StubRunAgent("fundamental_analysis", {"TEST": {"pe_ratio": 19.0}})
    orch.sentiment_agent = sentiment or CountingSpyAgent({"TEST": {"sentiment": "neutral"}})
    orch.risk_agent = CountingSpyAgent({"risk_by_symbol": {"TEST": {"beta": 1.1}}})
    orch.synthesis_agent = CountingSpyAgent({"audit": {"verdict": "pass"}})
    orch.decision_agent = CountingSpyAgent({"decisions": {"TEST": {"action": "hold"}}})
    orch.report_agent = CountingSpyAgent({"sections": {"overview": "ok"}})
    return orch


def _invoke(orch: MultiAgentOrchestrator, **state_kwargs) -> dict:
    # RED-phase guard: without the node-level bound a sleeping process()
    # stub hangs the graph forever — the outer wait_for turns that into a
    # 15s test failure instead of a hung suite.
    state = create_initial_state(query="q", symbols=["TEST"], **state_kwargs)
    return asyncio.run(asyncio.wait_for(orch.graph.ainvoke(state), timeout=15))


def test_hanging_process_agent_times_out_and_degrades() -> None:
    """A process() stub that never returns is bounded by timeout_per_agent:
    each attempt records a TimeoutError, retries drain the budget, the
    analysis branch degrades and everyone downstream still completes."""
    orch = _build_orchestrator(sentiment=SlowProcessAgent(delay=999.0))
    final = _invoke(orch, timeout_per_agent=0.15, max_retries=2)

    assert final["agent_status"]["sentiment_analysis"] == "failed"
    errors = [e for e in final["errors"] if e.get("agent") == "sentiment_analysis"]
    assert len(errors) == 2, "one error entry per attempt (max_retries=2)"
    assert all(e["type"] == "TimeoutError" for e in errors)
    assert all("timeout" in e["message"].lower() for e in errors)
    # Degraded branch: the rest of the pipeline still finishes.
    assert final["agent_status"]["data_collection"] == "completed"
    assert final["agent_status"]["report_generation"] == "completed"
    # Iteration 171: the failed attempt's duration is still recorded.
    assert 0.1 <= final["agent_timings"]["sentiment_analysis"] < 1.0


def test_zero_budget_disables_the_bound() -> None:
    """timeout_per_agent <= 0 is the documented escape hatch: a slow
    process() still completes instead of being cancelled."""
    orch = _build_orchestrator(sentiment=SlowProcessAgent(delay=0.25))
    final = _invoke(orch, timeout_per_agent=0)

    assert final["agent_status"]["sentiment_analysis"] == "completed"
    assert final["sentiment_analysis"] == {"TEST": {"sentiment": "neutral"}}


def test_default_budget_does_not_touch_fast_agents() -> None:
    """The default 300s bound never fires on well-behaved agents."""
    orch = _build_orchestrator(sentiment=SlowProcessAgent(delay=0.0))
    final = _invoke(orch)

    assert final["agent_status"]["sentiment_analysis"] == "completed"
    assert not final.get("errors")
