"""Pure rank-IC math for the decision layer (Grinold & Kahn style)."""

from __future__ import annotations

import pytest

from app.analysis.ic import (
    MIN_IC_SYMBOLS,
    decision_dimension_scores,
    decision_scores,
    ic_summary,
    information_coefficient,
)


class TestDecisionScores:
    def test_pipeline_shape(self) -> None:
        result = {
            "decision": {
                "decisions": {
                    "AAPL": {"symbol": "AAPL", "action": "buy", "score": 72.0},
                    "MSFT": {"symbol": "MSFT", "action": "hold", "score": 48.5},
                }
            }
        }
        assert decision_scores(result) == {"AAPL": 72.0, "MSFT": 48.5}

    def test_response_shape_and_unscored_entries_skipped(self) -> None:
        # Response-shaped results carry a top-level decisions list keyed by
        # composite_score; zero-evidence runs emit None — not a neutral vote.
        result = {
            "decisions": [
                {"symbol": "AAPL", "composite_score": 61.0},
                {"symbol": "MSFT", "composite_score": None},
                {"symbol": "NVDA", "composite_score": 80.0},
            ]
        }
        assert decision_scores(result) == {"AAPL": 61.0, "NVDA": 80.0}

    def test_missing_decisions_returns_empty(self) -> None:
        assert decision_scores({}) == {}
        assert decision_scores({"decision": {}}) == {}


class TestDecisionDimensionScores:
    def test_pipeline_shape_with_per_dimension_gaps(self) -> None:
        result = {
            "decision": {
                "decisions": {
                    "AAPL": {
                        "symbol": "AAPL",
                        "score": 72.0,
                        "component_scores": {"technical": 60.0, "fundamental": 80.0},
                    },
                    "MSFT": {
                        "symbol": "MSFT",
                        "score": 48.5,
                        "component_scores": {"technical": 55.0, "fundamental": None},
                    },
                }
            }
        }
        # MSFT's missing fundamental score simply drops it from that
        # dimension's cross-section — not a neutral vote.
        assert decision_dimension_scores(result) == {
            "technical": {"AAPL": 60.0, "MSFT": 55.0},
            "fundamental": {"AAPL": 80.0},
        }

    def test_missing_components_return_empty(self) -> None:
        assert decision_dimension_scores({}) == {}
        assert decision_dimension_scores({"decision": {"decisions": {"A": {"score": 1.0}}}}) == {}

    def test_response_list_shape(self) -> None:
        result = {
            "decisions": [
                {
                    "symbol": "AAPL",
                    "composite_score": 61.0,
                    "component_scores": {"sentiment": -20.0},
                }
            ]
        }
        assert decision_dimension_scores(result) == {"sentiment": {"AAPL": -20.0}}


class TestInformationCoefficient:
    def test_perfect_and_inverted_order(self) -> None:
        scores = {"A": 10.0, "B": 30.0, "C": 50.0, "D": 70.0}
        rising = {"A": 0.01, "B": 0.02, "C": 0.03, "D": 0.04}
        falling = {"A": 0.04, "B": 0.03, "C": 0.02, "D": 0.01}
        assert information_coefficient(scores, rising) == 1.0
        assert information_coefficient(scores, falling) == -1.0

    def test_needs_three_common_symbols(self) -> None:
        scores = {"A": 10.0, "B": 30.0, "C": 50.0}
        returns = {"A": 0.01, "B": 0.02}  # only two overlap
        assert information_coefficient(scores, returns) is None
        assert MIN_IC_SYMBOLS == 3

    def test_refuses_rank_constant_inputs(self) -> None:
        # Constant scores (or constant returns): correlation is undefined,
        # not zero — refuse rather than fabricate.
        scores = {"A": 50.0, "B": 50.0, "C": 50.0}
        returns = {"A": 0.01, "B": 0.02, "C": 0.03}
        assert information_coefficient(scores, returns) is None
        assert (
            information_coefficient(
                {"A": 1.0, "B": 2.0, "C": 3.0}, {"A": 0.02, "B": 0.02, "C": 0.02}
            )
            is None
        )


class TestICSummary:
    def test_grinold_kahn_math(self) -> None:
        # mean 0.2, ddof-1 std 0.3 -> icir 2/3, t = (2/3)*sqrt(3).
        summary = ic_summary([0.2, -0.1, 0.5])
        assert summary is not None
        assert summary["runs"] == 3
        assert summary["ic_mean"] == pytest.approx(0.2, abs=1e-6)
        assert summary["ic_std"] == pytest.approx(0.3, abs=1e-6)
        assert summary["icir"] == pytest.approx(2 / 3, abs=1e-6)
        assert summary["t_stat"] == pytest.approx((2 / 3) * 3**0.5, abs=1e-4)
        assert summary["ic_positive_rate"] == pytest.approx(2 / 3, abs=1e-4)

    def test_single_run_has_mean_but_no_icir(self) -> None:
        summary = ic_summary([0.3])
        assert summary is not None
        assert summary["runs"] == 1
        assert summary["ic_mean"] == pytest.approx(0.3)
        assert summary["icir"] is None
        assert summary["t_stat"] is None

    def test_empty_returns_none(self) -> None:
        assert ic_summary([]) is None
