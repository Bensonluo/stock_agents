"""Availability-aware weighting in derive_recommendation.

The composite used to hand every missing dimension a neutral-50 vote at
full weight: a CN name without financials collected 22.5 points of
"neutral" fundamental on zero evidence — the same missing-data-as-quality
anti-pattern the fundamental scorer dropped. These tests pin the
renormalization: weights ride only the dimensions that measured something,
full-data composites stay bit-identical, and zero evidence holds at zero
conviction instead of a confident sell.

The 2026-09-27 smoke added the market-data gate: renormalization must
stop where the only price-data dimension (technical) is unavailable —
surviving news sentiment used to ride the renormalized weights to a
confident directional call. Those runs now withhold direction entirely.
"""

from __future__ import annotations

from app.services.report_service import derive_recommendation

_FULL_FUND = {"overall_score": 60.0, "recommendation": "buy"}
_FULL_TECH = {"signals": {"trend": "bullish"}, "sentiment": {"score": 20.0}}
_FULL_SENT = {"score": 0.0, "article_count": 5}
_FULL_RISK = {"risk_level": "medium"}


def test_full_data_composite_is_bit_identical() -> None:
    result = derive_recommendation("T", _FULL_FUND, _FULL_TECH, _FULL_SENT, _FULL_RISK)

    # 60*.45 + 60*.30 + 50*.15 + 50*.10 = 57.5 — the classic blend.
    assert result["composite_score"] == 57.5
    assert result["action"] == "add"
    assert result["confidence"] == 0.58  # 0.55 + 2.5/100 rounded
    assert "unavailable" not in result["reasoning"]


def test_missing_fundamental_reweights_instead_of_neutral_vote() -> None:
    # Old behavior: fund defaulted to 50 -> 22.5 free points -> composite 53
    # -> "hold". Renormalized: 30.5/0.55 = 55.4545 -> 55.5 at 1 decimal.
    result = derive_recommendation("T", {}, _FULL_TECH, _FULL_SENT, _FULL_RISK)

    assert result["composite_score"] == 55.5
    assert result["action"] == "add"  # absence no longer drags to hold
    assert "fundamental unavailable" in result["reasoning"]


def test_only_technical_available_rides_it_alone() -> None:
    bullish = derive_recommendation(
        "T", {}, {"signals": {"trend": "bullish"}, "sentiment": {"score": 60.0}}, {}, {}
    )
    bearish = derive_recommendation(
        "T", {}, {"signals": {"trend": "bearish"}, "sentiment": {"score": -80.0}}, {}, {}
    )

    assert bullish["composite_score"] == 80.0  # (60+100)/2
    assert bullish["action"] == "buy"
    assert bearish["composite_score"] == 10.0  # (-80+100)/2
    assert bearish["action"] == "sell"


def test_zero_evidence_holds_at_zero_conviction() -> None:
    result = derive_recommendation("T", {}, {}, {}, {})

    assert result["action"] == "hold"
    assert result["confidence"] == 0.0
    assert result["composite_score"] is None
    assert "No dimension" in result["reasoning"]


def test_zero_article_sentiment_is_absence_not_neutrality() -> None:
    empty_feed = {"score": 0.0, "article_count": 0}

    excluded = derive_recommendation("T", _FULL_FUND, _FULL_TECH, empty_feed, _FULL_RISK)

    # 50/0.85 = 58.8235 -> 58.8 at 1 decimal — versus 57.5 when the same
    # zero score arrives from real articles (first test).
    assert excluded["composite_score"] == 58.8
    assert "sentiment unavailable" in excluded["reasoning"]


def test_zero_fundamental_score_is_not_fifty() -> None:
    # The old `or 50` coerced a genuine 0 (strong_sell) into a neutral vote.
    result = derive_recommendation(
        "T",
        {"overall_score": 0.0, "recommendation": "strong_sell"},
        _FULL_TECH,
        _FULL_SENT,
        _FULL_RISK,
    )

    assert result["composite_score"] == 30.5  # 0*.45 + 18 + 7.5 + 5
    assert result["action"] == "reduce"


def test_insufficient_risk_level_is_excluded() -> None:
    result = derive_recommendation(
        "T", _FULL_FUND, _FULL_TECH, _FULL_SENT, {"risk_level": "insufficient_data"}
    )

    # (60*.45 + 60*.30 + 50*.15)/0.90 = 52.5/0.90 = 58.33
    assert result["composite_score"] == 58.3
    assert "risk unavailable" in result["reasoning"]


def test_stale_cap_survives_the_rewrite() -> None:
    stale_tech = {**_FULL_TECH, "freshness": {"stale": True, "as_of": "2026-09-01"}}

    result = derive_recommendation("T", _FULL_FUND, stale_tech, _FULL_SENT, _FULL_RISK)

    assert result["confidence"] <= 0.4
    assert "stale" in result["reasoning"]


# ------------------------------------------------------------------
# Market-data gate (2026-09-27 production smoke)
#
# Yahoo 429 + East Money anti-crawl left symbols with no quotes at all;
# renormalized news sentiment alone still published directional calls
# ("sell" at 0.85 on 600000, "add" on AAPL). Without prices there is no
# direction to judge — the decision layer must withhold, not reweight.
# ------------------------------------------------------------------

_INCIDENT_SENT = {"score": -70.0, "article_count": 6}


def test_missing_technical_withholds_the_directional_call() -> None:
    # The exact incident shape: technical block wholly absent, bearish
    # news survived, risk degraded to insufficient_data.
    result = derive_recommendation(
        "600000", {}, {}, _INCIDENT_SENT, {"risk_level": "insufficient_data"}
    )

    assert result["action"] == "hold"
    assert result["confidence"] == 0.0
    assert result["composite_score"] is None
    assert "Market data unavailable" in result["reasoning"]
    assert "directional action withheld" in result["reasoning"]
    # Evidence stays visible even though it cannot drive the action.
    assert "sentiment -70" in result["reasoning"]


def test_bullish_news_alone_cannot_drive_an_add_either() -> None:
    result = derive_recommendation(
        "AAPL", {}, {}, {"score": 30.0, "article_count": 9}, {"risk_level": "high"}
    )

    assert result["action"] == "hold"
    assert result["confidence"] == 0.0


def test_fundamental_survivor_does_not_unlock_direction() -> None:
    # Renormalized fundamental + sentiment reached "buy" 0.72 on zero price
    # data — same hole, different survivor set.
    result = derive_recommendation(
        "T",
        {"overall_score": 80.0, "recommendation": "buy"},
        {},
        {"score": 30.0, "article_count": 5},
        _FULL_RISK,
    )

    assert result["action"] == "hold"
    assert result["confidence"] == 0.0
    assert result["composite_score"] is None


def test_insufficient_data_technical_block_is_absence_not_neutrality() -> None:
    # The pipeline's degraded block hardcodes sentiment.score = 0; the
    # renormalizer used to read that zero as a measured neutral technical
    # vote ("technical neutral/+0") and kept publishing direction.
    degraded_tech = {
        "status": "insufficient_data",
        "reason": "only 2 daily bars available (need 60)",
        "signals": {},
        "sentiment": {"score": 0, "sentiment": "hold", "strength": 0},
    }

    result = derive_recommendation("600000", {}, degraded_tech, _INCIDENT_SENT, _FULL_RISK)

    assert result["action"] == "hold"
    assert result["confidence"] == 0.0
    assert result["composite_score"] is None
    assert "Market data unavailable" in result["reasoning"]


def test_react_error_technical_block_is_gated() -> None:
    # A failed fetch tool stores {"_error": ...} as the technical block —
    # no sentiment score, so the gate fires on the ReAct path too.
    result = derive_recommendation(
        "AAPL", {}, {"_error": {"error": "fetch failed"}}, {"score": 30.0, "article_count": 9}, {}
    )

    assert result["action"] == "hold"
    assert result["confidence"] == 0.0


def test_gated_reasoning_keeps_every_survivor_visible() -> None:
    result = derive_recommendation(
        "T",
        {"overall_score": 62.0, "recommendation": "buy"},
        {},
        {"score": 20.0, "article_count": 4},
        _FULL_RISK,
    )

    assert "fundamental 62/buy" in result["reasoning"]
    assert "sentiment +20" in result["reasoning"]
    assert "risk medium" in result["reasoning"]


def test_decision_agent_seam_inherits_the_gate() -> None:
    # The pipeline decision agent wraps the shared formula; the incident
    # actions shipped from this seam. Parity: the gate must hold here too.
    import asyncio

    from app.agents.decision_agent import DecisionMakingAgent

    agent = DecisionMakingAgent("test-decision")
    decision = asyncio.run(
        agent._make_decision("600000", {}, {}, _INCIDENT_SENT, {"risk_level": "insufficient_data"})
    )

    assert decision["action"] == "hold"
    assert decision["confidence"] == 0.0
    assert decision["score"] is None
    assert "Market data unavailable" in decision["rationale"]
    # Zero-confidence holds keep the established low-confidence warning.
    assert any("Low confidence" in w for w in decision["warnings"])
    # Per-dimension evidence stays honest for IC attribution: technical is
    # absent (None), the measured sentiment value is preserved as-is.
    assert decision["component_scores"]["technical"] is None
    assert decision["component_scores"]["sentiment"] == -70.0


# --- regression invariants: every pre-gate path stays bit-identical ---


def test_only_risk_path_is_unchanged_by_the_gate() -> None:
    # Iteration 43-5: risk alone holds at zero conviction, exact wording.
    result = derive_recommendation("T", {}, {}, {}, {"risk_level": "low"})

    assert result == {
        "action": "hold",
        "confidence": 0.0,
        "composite_score": None,
        "reasoning": (
            "Only risk data available — risk alone cannot recommend; holding with zero conviction"
        ),
    }


def test_zero_evidence_reasoning_is_unchanged_by_the_gate() -> None:
    # The all-missing early return keeps its wording; the gate must not
    # reorder itself ahead of it.
    result = derive_recommendation("T", {}, {}, {}, {})

    assert result["action"] == "hold"
    assert result["reasoning"] == "No dimension has data to score; holding with zero conviction"


def test_stale_but_present_technical_is_not_gated() -> None:
    # Stale bars are data, not absence: the view stands, confidence capped
    # at 0.4 (iteration 23). Full bit-level pin alongside the <= 0.4 one.
    stale_tech = {**_FULL_TECH, "freshness": {"stale": True, "as_of": "2026-09-01"}}

    result = derive_recommendation("T", _FULL_FUND, stale_tech, _FULL_SENT, _FULL_RISK)

    assert result["action"] == "add"
    assert result["confidence"] == 0.4
    assert result["composite_score"] == 57.5
    assert "price data stale as of 2026-09-01" in result["reasoning"]


def test_fundamental_missing_technical_present_is_not_gated() -> None:
    # A-share common case (iteration 43 renormalization) — unchanged.
    result = derive_recommendation("T", {}, _FULL_TECH, _FULL_SENT, _FULL_RISK)

    assert result["composite_score"] == 55.5
    assert result["action"] == "add"
    assert result["confidence"] == 0.55
