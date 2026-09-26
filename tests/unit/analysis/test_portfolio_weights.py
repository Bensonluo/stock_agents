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


def test_per_symbol_caps_bind_the_allocation() -> None:
    # P1-3 repro at the allocator level: two buys whose risk/decision caps
    # are 5% each must not fall through to the allocator's uniform 20% cap.
    result = suggest_weights(
        {
            "A": {"conviction": 0.8, "volatility_annualized": 0.2},
            "B": {"conviction": 0.8, "volatility_annualized": 0.2},
        },
        caps={"A": 0.05, "B": 0.05},
    )

    assert result["weights"] == {"A": 0.05, "B": 0.05}
    assert result["cash_reserve"] == 0.9


def test_per_symbol_cap_redistributes_to_uncapped_names() -> None:
    result = suggest_weights(
        {
            "A": {"conviction": 0.9, "volatility_annualized": 0.2},  # raw 4.5
            "B": {"conviction": 0.45, "volatility_annualized": 0.2},  # raw 2.25
            "C": {"conviction": 0.45, "volatility_annualized": 0.2},  # raw 2.25
        },
        max_weight=0.6,
        caps={"A": 0.3},
    )

    # A's own 0.3 cap binds below the global 0.6; B and C split the freed
    # budget proportionally (their 0.25 shares of the 0.5 rest -> 0.35 each).
    assert result["weights"] == {"A": 0.3, "B": 0.35, "C": 0.35}
    assert result["cash_reserve"] == 0.0


def test_unusable_per_symbol_caps_fall_back_to_global() -> None:
    result = suggest_weights(
        {
            "A": {"conviction": 0.8, "volatility_annualized": 0.2},
            "B": {"conviction": 0.4, "volatility_annualized": 0.4},
        },
        max_weight=0.6,
        caps={"A": None, "B": -0.1},
    )

    assert result["weights"] == {"A": 0.6, "B": 0.4}


def _cap_shape_parity_keys() -> dict:
    # Canonical _normalize keys the cap-threading tests don't otherwise care
    # about, kept present for shape parity with the other report tests.
    return {
        "market_data": {},
        "technical_analysis": {},
        "fundamental_analysis": {},
        "sentiment_flat": {},
        "portfolio_risk": {},
        "research_synthesis": {},
        "overall_sentiment": {},
    }


def test_report_weights_respect_pipeline_decision_caps() -> None:
    c = {
        "symbols": ["A", "B"],
        "decisions": {
            "A": {
                "action": "buy",
                "confidence": 0.8,
                "score": 70,
                "position_size": {"percentage_of_portfolio": 5},
            },
            "B": {
                "action": "buy",
                "confidence": 0.8,
                "score": 68,
                "position_size": {"percentage_of_portfolio": 5},
            },
        },
        "risk_flat": {
            "A": {
                "metrics": {"volatility_annualized": 0.2},
                "position_recommendation": {"max_position_size": 5.0},
            },
            "B": {
                "metrics": {"volatility_annualized": 0.2},
                "position_recommendation": {"max_position_size": 5.0},
            },
        },
        **_cap_shape_parity_keys(),
    }

    summary = ReportService._recommendations(c)

    # The per-symbol recommendation says 5%; the portfolio suggestion must
    # not hand each name the allocator's uniform 20% cap.
    assert summary["suggested_weights"]["weights"] == {"A": 0.05, "B": 0.05}
    assert summary["suggested_weights"]["cash_reserve"] == 0.9


def test_report_weights_respect_react_flat_decision_caps() -> None:
    # Same repro through the ReAct gated shape: react_agent writes
    # position_size as a flat float (percent), not the pipeline's dict.
    c = {
        "symbols": ["A", "B"],
        "decisions": {
            "A": {
                "action": "buy",
                "confidence": 0.8,
                "score": 70,
                "position_size": 5.0,
                "committee_verdict": "limit",
            },
            "B": {
                "action": "buy",
                "confidence": 0.8,
                "score": 68,
                "position_size": 5.0,
                "committee_verdict": "limit",
            },
        },
        "risk_flat": {
            "A": {
                "metrics": {"volatility_annualized": 0.2},
                "position_recommendation": {"max_position_size": 5.0},
            },
            "B": {
                "metrics": {"volatility_annualized": 0.2},
                "position_recommendation": {"max_position_size": 5.0},
            },
        },
        **_cap_shape_parity_keys(),
    }

    summary = ReportService._recommendations(c)

    assert summary["suggested_weights"]["weights"] == {"A": 0.05, "B": 0.05}


def test_risk_only_cap_binds_when_no_decision_position() -> None:
    # Derived path: by_symbol entries carry no position_size, so the only
    # cap in play is the risk engine's max_position_size.
    c = {
        "symbols": ["A", "B"],
        "decisions": {},
        "risk_flat": {
            "A": {
                "metrics": {"volatility_annualized": 0.2},
                "position_recommendation": {"max_position_size": 5.0},
            },
            "B": {
                "metrics": {"volatility_annualized": 0.2},
                "position_recommendation": {"max_position_size": 5.0},
            },
        },
        **_cap_shape_parity_keys(),
    }
    summary = {
        "by_symbol": {
            "A": {"action": "buy", "confidence": 0.8},
            "B": {"action": "buy", "confidence": 0.6},
        }
    }

    weights = ReportService._suggested_weights(c, summary)

    assert weights["weights"]["A"] <= 0.05
    assert weights["weights"]["B"] <= 0.05


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
