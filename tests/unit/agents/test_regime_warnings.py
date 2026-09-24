"""Regime-conditional decision warnings — the actionable layer of iteration 76.

The regime block has been pure annotation since iteration 76 (narrative since
77); these tests pin the one place it is allowed to act: appending warning
strings to BUY decisions. Action/confidence/score/position must be identical
with and without a regime — pure annotation, pinned explicitly.
"""

from __future__ import annotations

import pytest

from app.agents.decision_agent import DecisionMakingAgent, _regime_warnings

_BEAR = {
    "status": "ok",
    "bars": 300,
    "trend": "bear",
    "volatility_regime": "elevated",
    "drawdown_from_52w_high": -0.24,
    "price_vs_sma200": -0.084,
    "vol_ratio_20d_vs_full": 1.4,
}

_BULL = {
    "status": "ok",
    "bars": 300,
    "trend": "bull",
    "volatility_regime": "normal",
    "drawdown_from_52w_high": -0.031,
    "price_vs_sma200": 0.064,
    "vol_ratio_20d_vs_full": 1.0,
}

# Enough evidence to land in the buy band (combined ~89): fund 90, tech 80
# (-> 90 normalized), sentiment 70 with articles (-> 85), no risk dimension.
_BUY_TECH = {"signals": {"trend": "bullish"}, "sentiment": {"score": 80}}
_BUY_FUND = {"overall_score": {"score": 90}}
_BUY_SENT = {"score": 70, "article_count": 3}


class TestRegimeWarningsPure:
    def test_bear_buy_gets_counter_trend_warning_with_number(self) -> None:
        warnings = _regime_warnings("buy", _BEAR)
        assert any("Counter-trend" in w for w in warnings)
        assert any("-8.4%" in w for w in warnings)

    def test_bear_buy_gets_all_three_warning_kinds(self) -> None:
        warnings = _regime_warnings("buy", _BEAR)
        assert len(warnings) == 3  # counter-trend + elevated vol + deep drawdown
        assert any("elevated" in w and "1.4x" in w for w in warnings)
        assert any("52-week high" in w and "24.0%" in w for w in warnings)

    def test_bear_sell_and_hold_get_nothing(self) -> None:
        assert _regime_warnings("sell", _BEAR) == []
        assert _regime_warnings("hold", _BEAR) == []

    def test_bull_buy_gets_nothing(self) -> None:
        assert _regime_warnings("buy", _BULL) == []

    def test_elevated_vol_alone_warns(self) -> None:
        regime = {**_BULL, "volatility_regime": "elevated", "vol_ratio_20d_vs_full": 1.6}
        warnings = _regime_warnings("buy", regime)
        assert len(warnings) == 1
        assert "elevated" in warnings[0] and "1.6x" in warnings[0]

    def test_deep_drawdown_alone_warns(self) -> None:
        regime = {**_BULL, "drawdown_from_52w_high": -0.27}
        warnings = _regime_warnings("buy", regime)
        assert len(warnings) == 1
        assert "52-week high" in warnings[0] and "27.0%" in warnings[0]

    def test_unknown_or_degraded_regimes_refuse(self) -> None:
        assert _regime_warnings("buy", None) == []
        assert _regime_warnings("buy", {"status": "insufficient_history"}) == []

    def test_missing_numeric_keys_still_warn_without_numbers(self) -> None:
        # A bear label without the optional numeric context still warns —
        # degraded regimes degrade gracefully, they do not go silent.
        regime = {"status": "ok", "trend": "bear"}
        warnings = _regime_warnings("buy", regime)
        assert len(warnings) == 1
        assert "%" not in warnings[0]


@pytest.mark.asyncio
class TestDecisionLevelAnnotation:
    async def test_buy_decision_carries_regime_warnings(self) -> None:
        agent = DecisionMakingAgent("test-decision")

        decision = await agent._make_decision(
            "AAA", _BUY_TECH, _BUY_FUND, _BUY_SENT, {}, market_regime=_BEAR
        )

        assert decision["action"] == "buy"
        assert any("Counter-trend" in w for w in decision["warnings"])

    async def test_decision_numbers_identical_with_and_without_regime(self) -> None:
        agent = DecisionMakingAgent("test-decision")

        plain = await agent._make_decision("AAA", _BUY_TECH, _BUY_FUND, _BUY_SENT, {})
        hostile = await agent._make_decision(
            "AAA", _BUY_TECH, _BUY_FUND, _BUY_SENT, {}, market_regime=_BEAR
        )

        # Pure annotation: the regime can add warnings, nothing else.
        assert hostile["action"] == plain["action"]
        assert hostile["confidence"] == plain["confidence"]
        assert hostile["score"] == plain["score"]
        assert hostile["position_size"] == plain["position_size"]
        assert set(plain["warnings"]) < set(hostile["warnings"])

    async def test_process_routes_regime_into_decision_warnings(self) -> None:
        agent = DecisionMakingAgent("test-decision")

        result = await agent.process(
            {
                "symbols": ["AAA"],
                "technical_analysis": {"AAA": _BUY_TECH},
                "fundamental_analysis": {"AAA": _BUY_FUND},
                "sentiment_analysis": {"AAA": _BUY_SENT},
                "risk_assessment": {
                    "risk_by_symbol": {"AAA": {}},
                    "market_regime": _BEAR,
                },
            }
        )

        warnings = result["decisions"]["AAA"]["warnings"]
        assert any("Counter-trend" in w for w in warnings)
