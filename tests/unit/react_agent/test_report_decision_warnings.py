"""Decision warnings on the ReAct report path's gated decisions.

The production ReAct path builds its decisions in
``_build_report_data`` — committee-gated derived recs under the NESTED
``data["decision"]["decisions"]`` shape ``_normalize`` prefers. Those
decisions carried none of the warning generators the pipeline decision
agent emits (low-confidence notices, high-risk buys, regime-conditional
buyer risk), so iteration 80's regime warnings could never reach a ReAct
user even after the risk tool started attaching the regime (iteration
115). Warnings must attach to the POST-GATE action/confidence — a vetoed
buy no longer exists, so describing its counter-trend risk would be
narrating a decision the committee already refused.
"""

from __future__ import annotations

from app.react_agent import react_agent

BEAR_REGIME = {
    "status": "ok",
    "bars": 210,
    "trend": "bear",
    "price_vs_sma200": -0.417,
    # Extra warning conditions deliberately OFF — the counter-trend
    # warning must fire alone, not buried among neighbors.
    "volatility_regime": "normal",
    "drawdown_from_52w_high": -0.05,
}


def _synthesis(verdict: str) -> dict:
    return {
        "audit": {"verdict": "pass"},
        "per_symbol": {
            "TEST": {"committee": {"verdict": verdict, "position_cap_pct": None, "conditions": []}}
        },
    }


def _state(
    regime: dict | None = None,
    stale_technical: bool = False,
    option_implied: dict | None = None,
) -> dict:
    technical: dict = {"signals": {"trend": "bullish"}, "sentiment": {"score": 80}}
    if stale_technical:
        technical["freshness"] = {"as_of": "2026-09-01", "age_days": 25, "stale": True}
    assess_risk: dict = {
        "TEST": {"symbol": "TEST", "risk_level": "medium", "risk_score": 45, "metrics": {}},
    }
    if regime is not None:
        # Namespaced key exactly as assess_risk attaches it (iteration 115).
        assess_risk["market_regime"] = regime
    if option_implied is not None:
        # Namespaced key exactly as assess_risk attaches it (iteration 156).
        assess_risk["option_implied"] = option_implied
    return {
        "symbols": ["TEST"],
        "tool_results": {
            "analyze_technical": {"TEST": technical},
            "analyze_fundamental": {"TEST": {"overall_score": {"score": 80}}},
            "analyze_sentiment": {
                "TEST": {"sentiment": {"score": 70, "article_count": 3}, "overall_sentiment": {}}
            },
            "assess_risk": assess_risk,
            "calculate_position_size": {"TEST": {"position_size": 10.0}},
        },
    }


def _decision(monkeypatch, verdict: str, state: dict) -> dict:
    monkeypatch.setattr(react_agent, "synthesize", lambda data: _synthesis(verdict))
    return react_agent._build_report_data(state)["decision"]["decisions"]["TEST"]


class TestApprovedBuys:
    def test_buy_in_bear_regime_carries_counter_trend_warning(self, monkeypatch) -> None:
        decision = _decision(monkeypatch, "approve", _state(regime=BEAR_REGIME))

        assert decision["action"] == "buy"
        assert len(decision["warnings"]) == 1
        assert "Counter-trend entry" in decision["warnings"][0]

    def test_buy_without_regime_omits_warnings(self, monkeypatch) -> None:
        decision = _decision(monkeypatch, "approve", _state(regime=None))

        assert decision["action"] == "buy"
        assert "warnings" not in decision


class TestGateSemantics:
    def test_vetoed_buy_omits_counter_trend_warning(self, monkeypatch) -> None:
        """Post-gate warnings: the veto already refused the buy — narrating
        its counter-trend risk would describe a decision that no longer
        exists. The gate caps confidence at exactly 0.5 (not below), so the
        low-confidence notice stays quiet too."""
        decision = _decision(monkeypatch, "veto", _state(regime=BEAR_REGIME))

        assert decision["action"] == "hold"
        assert "warnings" not in decision


class TestLowConfidence:
    def test_stale_capped_confidence_warns(self, monkeypatch) -> None:
        decision = _decision(monkeypatch, "approve", _state(regime=None, stale_technical=True))

        assert decision["action"] == "buy"
        assert decision["warnings"] == [
            "Low confidence in this recommendation. Consider waiting for clearer signals."
        ]


OPTION_COMPLACENT = {
    "status": "ok",
    "regime": "自满",
    "qvix": {"current": 14.85, "as_of": "2026-09-29", "percentile_1y": 0.1389},
    "iv": {},
    "pcr": {},
    "generated_at": "2026-09-30T10:00:00",
}


class TestOptionRegimeWarnings:
    """Iteration 155's option-implied block appends the same buy-side
    warnings on the ReAct path — annotation-only, post-gate, same shared
    generator as the pipeline decision agent."""

    def test_approved_buy_under_complacent_options_carries_warning(self, monkeypatch) -> None:
        decision = _decision(
            monkeypatch, "approve", _state(regime=None, option_implied=OPTION_COMPLACENT)
        )

        assert decision["action"] == "buy"
        assert len(decision["warnings"]) == 1
        assert "complacent" in decision["warnings"][0]
