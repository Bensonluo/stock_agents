"""The LLM decision synthesis must survive zero-evidence decisions.

derive_recommendation now returns composite_score=None when no directional
dimension has data (risk is a modifier, never a signal). The synthesis layer
used to format that None with :.0f — TypeError, and the except branch
silently degraded the whole summary to {}. These tests pin the None-safe
rendering and the top_pick tie-break.
"""

from __future__ import annotations

import pytest

from app.agents.decision_agent import DecisionMakingAgent

pytestmark = pytest.mark.asyncio


class _StubLLM:
    """Captures prompts; answers with a fixed synthesis string."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def __call__(self, prompt: str, **kwargs) -> str:
        self.prompts.append(prompt)
        return "Balanced portfolio summary."


def _agent_with_stub() -> tuple[DecisionMakingAgent, _StubLLM]:
    agent = DecisionMakingAgent("test-decision")
    stub = _StubLLM()
    agent.invoke_llm = stub  # type: ignore[method-assign]
    return agent, stub


async def test_none_score_renders_as_na_and_synthesis_survives() -> None:
    agent, stub = _agent_with_stub()

    result = await agent._llm_decision_synthesis(
        {"AAA": {"action": "hold", "confidence": 0.0, "score": None}}
    )

    assert result["synthesis"] == "Balanced portfolio summary."
    assert "score: n/a" in stub.prompts[0]
    assert result["top_pick"] == "AAA"


async def test_top_pick_prefers_real_scores_over_none() -> None:
    agent, _ = _agent_with_stub()

    result = await agent._llm_decision_synthesis(
        {
            "AAA": {"action": "hold", "confidence": 0.0, "score": None},
            "BBB": {"action": "add", "confidence": 0.6, "score": 72.5},
        }
    )

    assert result["top_pick"] == "BBB"


async def test_portfolio_summary_counts_zero_evidence_holds() -> None:
    agent = DecisionMakingAgent("test-decision")

    summary = agent._create_portfolio_summary(
        {
            "AAA": {"action": "hold", "confidence": 0.0},
            "BBB": {"action": "buy", "confidence": 0.8},
        }
    )

    assert summary["total_symbols"] == 2
    assert summary["hold_recommendations"] == 1
    assert summary["buy_recommendations"] == 1
    assert summary["avg_confidence"] == pytest.approx(0.4)
