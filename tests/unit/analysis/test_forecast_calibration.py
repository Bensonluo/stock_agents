"""Forecast calibration pure functions — hand-computed pins.

Brier, Brier skill score, reliability buckets, and the directional-claim
extractor that feeds them from stored decision history.
"""

from __future__ import annotations

from app.analysis.forecast_calibration import (
    brier_score,
    brier_skill_score,
    claim_correct,
    directional_claims,
    reliability_curve,
)


class TestBrier:
    def test_hand_computed(self) -> None:
        # (1-0.8)^2 + (0-0.6)^2 = 0.04 + 0.36, over 2 -> 0.2
        assert brier_score([(0.8, True), (0.6, False)]) == 0.2

    def test_perfect_and_terrible(self) -> None:
        assert brier_score([(1.0, True), (0.0, False)]) == 0.0
        assert brier_score([(1.0, False), (0.0, True)]) == 1.0

    def test_empty_refuses(self) -> None:
        assert brier_score([]) is None


class TestBrierSkillScore:
    def test_beating_the_base_rate(self) -> None:
        # base rate 0.5 -> brier_base 0.25; brier 0.01 -> 1 - 0.04 = 0.96
        assert brier_skill_score([(0.9, True), (0.1, False)]) == 0.96

    def test_losing_to_the_base_rate_is_negative(self) -> None:
        # brier 0.265 vs base 0.25 -> 1 - 1.06 = -0.06: confident and wrong
        assert brier_skill_score([(0.8, True), (0.7, False)]) == -0.06

    def test_identical_outcomes_undefined(self) -> None:
        # base-rate forecaster is perfect on a constant sample — skill is
        # undefined, not infinite.
        assert brier_skill_score([(0.8, True), (0.9, True)]) is None

    def test_empty_refuses(self) -> None:
        assert brier_skill_score([]) is None


class TestReliabilityCurve:
    def test_buckets_with_sample_sizes(self) -> None:
        curve = reliability_curve([(0.8, True), (0.9, True), (0.55, False), (1.0, True)])
        assert len(curve) == 2
        low, high = curve
        assert (low["bin_low"], low["bin_high"]) == (0.4, 0.6)
        assert low["n"] == 1
        assert low["empirical_rate"] == 0.0
        assert (high["bin_low"], high["bin_high"]) == (0.8, 1.0)
        assert high["n"] == 3  # 1.0 clamps into the top bin
        assert high["avg_confidence"] == 0.9
        assert high["empirical_rate"] == 1.0

    def test_decimal_boundary_falls_in_upper_bin(self) -> None:
        # 0.6 with 5 bins: float 0.6*5 lands at 2.999... or 3.0 depending on
        # representation — the epsilon pins it to the [0.6, 0.8) bin.
        curve = reliability_curve([(0.6, True)])
        assert curve[0]["bin_low"] == 0.6

    def test_empty_bins_omitted(self) -> None:
        curve = reliability_curve([(0.1, True), (0.15, False)])
        assert len(curve) == 1
        assert curve[0]["bin_low"] == 0.0
        assert curve[0]["empirical_rate"] == 0.5


class TestDirectionalClaims:
    def test_pipeline_shape_filters_and_normalizes(self) -> None:
        result = {
            "decision": {
                "decisions": {
                    "A": {"symbol": "A", "action": "buy", "confidence": 0.8},
                    "B": {"symbol": "B", "action": "strong_sell", "confidence": 0.6},
                    "C": {"symbol": "C", "action": "hold", "confidence": 0.9},
                    "D": {"symbol": "D", "action": "buy", "confidence": None},
                    "E": {"symbol": "E", "action": "buy", "confidence": 1.5},
                    "F": {"symbol": "F", "action": "moderate_buy", "confidence": 0.55},
                    "G": {"symbol": "G", "action": "buy", "confidence": "high"},
                }
            }
        }
        claims = directional_claims(result)
        assert claims["A"] == ("buy", 0.8)
        assert claims["B"] == ("sell", 0.6)  # strong_sell carries the sell claim
        assert claims["F"] == ("buy", 0.55)  # moderate_buy carries the buy claim
        assert set(claims) == {"A", "B", "F"}

    def test_response_list_shape(self) -> None:
        result = {
            "decisions": [
                {"symbol": "X", "action": "sell", "confidence": 0.4},
                {"symbol": "Y", "action": "hold", "confidence": 0.99},
            ]
        }
        claims = directional_claims(result)
        assert claims == {"X": ("sell", 0.4)}


class TestClaimCorrect:
    def test_buy_direction(self) -> None:
        assert claim_correct("buy", 0.10)
        assert not claim_correct("buy", -0.05)

    def test_sell_direction(self) -> None:
        assert claim_correct("sell", -0.10)
        assert not claim_correct("sell", 0.02)

    def test_flat_outcome_fails_both_directions(self) -> None:
        # Strict inequality — an uninformative market pays no correctness credit.
        assert not claim_correct("buy", 0.0)
        assert not claim_correct("sell", 0.0)
