"""The LLM decision synthesis must survive zero-evidence decisions.

derive_recommendation now returns composite_score=None when no directional
dimension has data (risk is a modifier, never a signal). The synthesis layer
used to format that None with :.0f — TypeError, and the except branch
silently degraded the whole summary to {}. These tests pin the None-safe
rendering and the top_pick tie-break.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.agents.decision_agent import DecisionMakingAgent, _market_context_line

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


_REGIME = {
    "status": "ok",
    "bars": 300,
    "trend": "bull",
    "volatility_regime": "elevated",
    "drawdown_from_52w_high": -0.0312,
    "price_vs_sma200": 0.0641,
    "vol_ratio_20d_vs_full": 1.4,
}


class TestRegimeAwareSynthesis:
    async def test_market_context_line_renders_the_regime(self) -> None:
        line = _market_context_line(_REGIME)

        assert line is not None
        assert "uptrend" in line
        assert "+6.4%" in line
        assert "elevated" in line
        assert "1.4x" in line
        assert "3.1%" in line

    def test_market_context_refuses_unknown_regimes(self) -> None:
        assert _market_context_line(None) is None
        assert _market_context_line({"status": "insufficient_history"}) is None
        # ok block with nothing classifiable to say
        assert _market_context_line({"status": "ok", "bars": 70}) is None

    async def test_synthesis_prompt_carries_market_context(self) -> None:
        agent, stub = _agent_with_stub()

        await agent._llm_decision_synthesis(
            {"AAA": {"action": "buy", "confidence": 0.7, "score": 72.0}}, _REGIME
        )

        assert "Market context:" in stub.prompts[0]
        assert "uptrend" in stub.prompts[0]

    async def test_synthesis_prompt_without_regime_is_unchanged(self) -> None:
        agent, stub = _agent_with_stub()

        await agent._llm_decision_synthesis(
            {"AAA": {"action": "buy", "confidence": 0.7, "score": 72.0}}
        )

        assert "Market context" not in stub.prompts[0]

    async def test_process_extracts_regime_from_risk_state(self) -> None:
        agent, stub = _agent_with_stub()
        agent.llm = stub  # make the synthesis branch fire
        agent._make_decision = AsyncMock(
            return_value={  # type: ignore[method-assign]
                "symbol": "AAA",
                "action": "buy",
                "confidence": 0.7,
                "score": 72.0,
                "component_scores": {},
                "position_size": {},
                "price_targets": {},
                "rationale": "",
                "warnings": [],
            }
        )

        result = await agent.process(
            {
                "symbols": ["AAA"],
                "technical_analysis": {},
                "fundamental_analysis": {},
                "sentiment_analysis": {},
                "risk_assessment": {
                    "risk_by_symbol": {"AAA": {}},
                    "market_regime": _REGIME,
                },
            }
        )

        assert result["llm_summary"]["synthesis"] == "Balanced portfolio summary."
        assert "Market context:" in stub.prompts[0]


class TestNullScoreExtractors:
    """Degraded blocks carry ``score: null`` — extractors must read that as
    missing evidence (None), not crash on (None - 50) and not coerce it to
    a real 0.0 sample.

    Found by the post-deploy smoke run (2026-09-25): a Yahoo-429 degraded
    run emitted ``overall_score.score = null`` and the fundamental extractor
    raised TypeError, dropping the symbol's decision to the error fallback
    (hold with zero confidence and an error rationale) instead of the
    formula path. Same ``.get(key, default)`` trap as iteration 62's
    score_news — the default only fires when the key is ABSENT.

    The 2026-09-26 review (P1-4) tightened the contract further: the stored
    value for a missing dimension is None. ic_service's dimension
    attribution treats a stored 0.0 as a measured neutral sample, so the
    old 0.0 coercion fabricated IC evidence for symbols that never had
    that dimension's data.
    """

    async def test_null_fundamental_score_reads_as_missing(self) -> None:
        agent = DecisionMakingAgent("test-decision")
        score = agent._extract_fundamental_score(
            {"overall_score": {"score": None, "rating": "insufficient_data"}}
        )
        assert score is None

    async def test_null_technical_and_sentiment_scores_read_as_missing(self) -> None:
        agent = DecisionMakingAgent("test-decision")
        assert agent._extract_technical_score({"sentiment": {"score": None}}) is None
        assert agent._extract_sentiment_score({"score": None}) is None

    async def test_degraded_run_uses_the_formula_path_not_the_error_fallback(
        self, monkeypatch
    ) -> None:
        # The exact shape of the smoke run: null-score fundamental, empty
        # technical, zero-article sentiment, insufficient risk.
        import app.services.ic_service as ic_service_module

        async def static_provider(**kwargs):
            from app.analysis.ic import STATIC_DIMENSION_WEIGHTS

            return dict(STATIC_DIMENSION_WEIGHTS), {
                "mode": "static",
                "weights": dict(STATIC_DIMENSION_WEIGHTS),
            }

        monkeypatch.setattr(ic_service_module, "get_adaptive_dimension_weights", static_provider)

        agent = DecisionMakingAgent("test-decision")
        agent.llm = None

        result = await agent.process(
            {
                "symbols": ["AAPL"],
                "technical_analysis": {},
                "fundamental_analysis": {
                    "AAPL": {"overall_score": {"score": None, "status": "insufficient_data"}}
                },
                "sentiment_analysis": {
                    "sentiment_by_symbol": {"AAPL": {"score": 0, "article_count": 0}}
                },
                "risk_assessment": {
                    "risk_by_symbol": {"AAPL": {"risk_level": "insufficient_data"}}
                },
            }
        )

        decision = result["decisions"]["AAPL"]
        # Formula path: canonical rationale + None for the missing dimension —
        # NOT the "Decision engine error" fallback rationale.
        assert "Decision engine error" not in decision["rationale"]
        assert decision["component_scores"]["fundamental"] is None
        assert decision["action"] == "hold"


class TestComponentScoresPreserveMissingAsNone:
    """The IC attribution loop consumes ``component_scores`` as measured
    samples (ic_service -> decision_dimension_scores): a missing dimension
    must surface as None, never a coerced 0.0 (2026-09-26 review, P1-4).
    """

    async def test_missing_blocks_surface_none_not_zero(self) -> None:
        agent = DecisionMakingAgent("test-decision")
        assert agent._extract_fundamental_score({}) is None
        assert agent._extract_fundamental_score({"overall_score": {"score": None}}) is None
        assert agent._extract_technical_score({}) is None
        assert agent._extract_technical_score({"sentiment": {"score": None}}) is None
        assert agent._extract_sentiment_score({}) is None
        assert agent._extract_sentiment_score({"score": None}) is None

    async def test_measured_scores_still_extract(self) -> None:
        agent = DecisionMakingAgent("test-decision")
        assert agent._extract_fundamental_score({"overall_score": {"score": 80}}) == 60.0
        assert agent._extract_technical_score({"sentiment": {"score": -40}}) == -40
        assert agent._extract_sentiment_score({"score": 25}) == 25

    async def test_neutral_fifty_is_a_real_zero_not_a_missing_dimension(self) -> None:
        # (50-50)*2 = 0.0 from a MEASURED overall score: a genuine neutral
        # vote, distinct from the None a missing dimension carries.
        agent = DecisionMakingAgent("test-decision")
        assert agent._extract_fundamental_score({"overall_score": {"score": 50}}) == 0.0
