"""Conviction-tilted inverse-volatility portfolio weights.

suggest_weights is the deterministic allocation layer: weights ∝
conviction / volatility with an iterative per-symbol cap and a cash
residue. Also pins the ReportService wiring that finally consumes the
risk engine's concentration_hhi (dead since the engine was extracted).
"""

from __future__ import annotations

from app.analysis.portfolio import suggest_weights
from app.services.report_service import ReportService


def test_weights_follow_conviction_over_volatility() -> None:
    result = suggest_weights(
        {
            "A": {"conviction": 0.8, "volatility_annualized": 0.2},  # raw 4.0
            "B": {"conviction": 0.4, "volatility_annualized": 0.4},  # raw 1.0
        },
        max_weight=0.6,
    )

    assert result["weights"]["A"] == 0.6  # capped from 0.8
    assert result["weights"]["B"] == 0.4  # gets the freed budget
    assert result["cash_reserve"] == 0.0
    assert result["concentration_hhi"] == 0.52  # 0.6^2 + 0.4^2


def test_uncapped_case_is_plain_proportional() -> None:
    result = suggest_weights(
        {
            "A": {"conviction": 0.5, "volatility_annualized": 0.25},
            "B": {"conviction": 0.5, "volatility_annualized": 0.25},
        },
        max_weight=0.9,
    )

    assert result["weights"] == {"A": 0.5, "B": 0.5}


def test_all_capped_spills_to_cash_reserve() -> None:
    result = suggest_weights(
        {
            "A": {"conviction": 0.9, "volatility_annualized": 0.2},
            "B": {"conviction": 0.9, "volatility_annualized": 0.2},
            "C": {"conviction": 0.9, "volatility_annualized": 0.2},
        },
        max_weight=0.3,
    )

    # Equal 1/3 shares all exceed the cap -> each capped, 10% stays in cash.
    assert result["weights"] == {"A": 0.3, "B": 0.3, "C": 0.3}
    assert result["cash_reserve"] == 0.1


def test_unusable_inputs_are_excluded_and_noted() -> None:
    result = suggest_weights(
        {
            "A": {"conviction": 0.8, "volatility_annualized": 0.2},
            "B": {"conviction": 0.4, "volatility_annualized": 0.4},
            "NO_CONV": {"conviction": None, "volatility_annualized": 0.3},
            "ZERO_VOL": {"conviction": 0.9, "volatility_annualized": 0.0},
            "NEG": {"conviction": 0.0, "volatility_annualized": 0.3},
        },
        max_weight=0.6,
    )

    assert set(result["weights"]) == {"A", "B"}
    assert result["excluded"] == ["NO_CONV", "ZERO_VOL", "NEG"]


def test_fewer_than_two_eligible_is_none() -> None:
    single = {"A": {"conviction": 0.8, "volatility_annualized": 0.2}}
    assert suggest_weights(single) is None
    assert suggest_weights({}) is None


def test_report_recommendations_carry_suggested_weights() -> None:
    c = {
        "symbols": ["A", "B", "C"],
        "decisions": {
            "A": {"action": "buy", "confidence": 0.8, "score": 70},
            "B": {"action": "strong_buy", "confidence": 0.4, "score": 60},
            "C": {"action": "sell", "confidence": 0.9, "score": 20},
        },
        "risk_flat": {
            "A": {"metrics": {"volatility_annualized": 0.2}},
            "B": {"metrics": {"volatility_annualized": 0.4}},
            "C": {"metrics": {"volatility_annualized": 0.2}},
        },
        # _recommendations_from_decisions reads only the decisions map, but
        # keep the other canonical keys present for shape parity.
        "market_data": {},
        "technical_analysis": {},
        "fundamental_analysis": {},
        "sentiment_flat": {},
        "portfolio_risk": {},
        "research_synthesis": {},
        "overall_sentiment": {},
    }

    summary = ReportService._recommendations(c)

    # C is a sell -> no allocation. With the default 20% cap both buyers
    # cap out and 60% stays in cash.
    assert summary["suggested_weights"]["weights"] == {"A": 0.2, "B": 0.2}
    assert summary["suggested_weights"]["cash_reserve"] == 0.6
    assert "C" not in summary["suggested_weights"]["weights"]


def test_report_without_eligible_buys_has_no_weights_block() -> None:
    c = {
        "symbols": ["A"],
        "decisions": {"A": {"action": "hold", "confidence": 0.4, "score": 50}},
        "risk_flat": {"A": {"metrics": {"volatility_annualized": 0.2}}},
        "market_data": {},
        "technical_analysis": {},
        "fundamental_analysis": {},
        "sentiment_flat": {},
        "portfolio_risk": {},
        "research_synthesis": {},
        "overall_sentiment": {},
    }

    summary = ReportService._recommendations(c)

    assert summary["suggested_weights"] is None
