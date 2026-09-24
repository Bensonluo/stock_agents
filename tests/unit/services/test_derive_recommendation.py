"""Availability-aware weighting in derive_recommendation.

The composite used to hand every missing dimension a neutral-50 vote at
full weight: a CN name without financials collected 22.5 points of
"neutral" fundamental on zero evidence — the same missing-data-as-quality
anti-pattern the fundamental scorer dropped. These tests pin the
renormalization: weights ride only the dimensions that measured something,
full-data composites stay bit-identical, and zero evidence holds at zero
conviction instead of a confident sell.
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
