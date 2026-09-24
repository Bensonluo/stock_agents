"""Achievable-max normalization of the fundamental component scores.

Ratings used to divide the raw component score by a hardcoded 100 — a
PE-only name can earn at most 30 points, so every PE-only valuation read
"poor" regardless of how cheap the PE was. These tests pin the fix: score
is normalized by the achievable maximum of the metrics actually present,
full-data scores stay bit-identical (each spec table sums to 100).
"""

from __future__ import annotations

from app.analysis.fundamental.scoring import analyze_fundamental_scoring


def test_pe_only_name_rides_its_own_achievable_max() -> None:
    result = analyze_fundamental_scoring({"S": {"metrics": {"pe_ratio": 12.0}}})["S"]

    valuation = result["valuation"]
    assert valuation["score"] == 100.0  # 30 raw of 30 achievable, not 30/100
    assert valuation["rating"] == "excellent"
    assert valuation["metrics_count"] == 1
    assert valuation["status"] == "available"


def test_mixed_quality_partial_data_scores_by_achievable_share() -> None:
    # pe 50 earns 0 of 30; pb 0.8 earns 25 of 25 -> 25/55 = 45.45.
    result = analyze_fundamental_scoring({"S": {"metrics": {"pe_ratio": 50.0, "pb_ratio": 0.8}}})[
        "S"
    ]

    assert result["valuation"]["score"] == 45.45
    assert result["valuation"]["metrics_count"] == 2


def test_full_metric_coverage_stays_bit_identical() -> None:
    metrics = {
        "pe_ratio": 12.0,
        "pb_ratio": 0.8,
        "ps_ratio": 1.5,
        "ev_ebitda": 6.0,
    }

    result = analyze_fundamental_scoring({"S": {"metrics": metrics}})["S"]

    # All top tiers: raw == achievable == 100; the normalization is a no-op.
    assert result["valuation"]["score"] == 100.0


def test_negative_debt_to_equity_scores_zero_not_moderate() -> None:
    # Negative equity is distress; the old elif chain handed it 30 of 40.
    result = analyze_fundamental_scoring({"S": {"metrics": {"debt_to_equity": -0.3}}})["S"]

    health = result["financial_health"]
    assert health["score"] == 0.0
    assert health["rating"] == "very_poor"


def test_zero_debt_earns_the_full_leverage_points() -> None:
    result = analyze_fundamental_scoring({"S": {"metrics": {"debt_to_equity": 0.0}}})["S"]

    assert result["financial_health"]["score"] == 100.0  # 40 of 40


def test_non_positive_pe_is_not_cheap() -> None:
    result = analyze_fundamental_scoring({"S": {"metrics": {"pe_ratio": 0.0}}})["S"]

    assert result["valuation"]["score"] == 0.0


def test_nan_metric_is_never_a_scoreable_observation() -> None:
    result = analyze_fundamental_scoring({"S": {"metrics": {"roe": float("nan"), "roa": 0.10}}})[
        "S"
    ]

    profitability = result["profitability"]
    assert profitability["details"] == {"roa": 0.10}  # NaN skipped, not stored
    assert profitability["score"] == 100.0  # 20 raw of 20 achievable
