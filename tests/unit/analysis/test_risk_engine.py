"""Specification tests for the deterministic risk engine."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from app.analysis.risk import (
    calculate_beta,
    concentration_hhi,
    correlation_matrix,
    cvar_historical,
    relative_risk_metrics,
    sortino_ratio,
    stress_scenarios,
    volatility_percentile,
)
from app.tools.risk.assessment import assess_risk


def _history(returns: np.ndarray, *, start: date = date(2024, 1, 1)) -> dict[str, list]:
    prices = [100.0]
    for value in returns:
        prices.append(prices[-1] * (1 + float(value)))
    dates = [(start + timedelta(days=i)).isoformat() for i in range(len(prices))]
    return {"dates": dates, "close": prices}


class TestLossMetrics:
    def test_cvar_is_at_least_as_bad_as_var(self) -> None:
        rng = np.random.default_rng(7)
        returns = rng.normal(0.0005, 0.02, 500)

        var_95 = float(np.percentile(returns, 5))
        cvar_95 = cvar_historical(returns, level=0.95)

        assert cvar_95 is not None
        assert cvar_95 <= var_95

    def test_too_few_observations_return_none(self) -> None:
        assert cvar_historical(np.array([0.01, -0.02])) is None
        assert sortino_ratio(np.array([0.01, -0.02])) is None

    def test_sortino_none_without_downside(self) -> None:
        returns = np.full(50, 0.001)

        assert sortino_ratio(returns) is None

    def test_sortino_positive_for_steady_gains(self) -> None:
        returns = np.full(60, 0.002)
        returns[3] = -0.01  # small downside

        assert sortino_ratio(returns) > 0

    def test_volatility_percentile_spikes_in_regime_change(self) -> None:
        calm_then_storm = np.concatenate([np.full(60, 0.001), np.full(5, 0.05)])

        percentile = volatility_percentile(calm_then_storm)

        # Current storm sits near the top of its own rolling history; the only
        # higher window is the regime-transition one itself.
        assert percentile > 0.9


class TestRelativeMetrics:
    def test_scaled_benchmark_gives_beta_alpha_r2(self) -> None:
        benchmark = np.array([(-1 if i % 4 == 0 else 1) * (0.002 + i * 0.0005) for i in range(120)])
        stock = benchmark * 1.6

        metrics = relative_risk_metrics(stock, benchmark)

        assert metrics["beta"] == pytest.approx(1.6, abs=1e-6)
        assert metrics["r_squared"] == pytest.approx(1.0)
        assert metrics["alpha_annualized"] == pytest.approx(0.0, abs=1e-4)

    def test_inadequate_overlap_returns_nones(self) -> None:
        metrics = relative_risk_metrics(np.full(5, 0.01), np.full(5, 0.01))

        assert metrics == {
            "beta": None,
            "alpha_annualized": None,
            "r_squared": None,
            "correlation": None,
        }

    def test_calculate_beta_needs_min_observations(self) -> None:
        assert calculate_beta(np.full(10, 0.01), np.full(10, 0.01)) is None


class TestStressAndPortfolio:
    def test_stress_scenarios_scale_with_beta(self) -> None:
        stress = stress_scenarios(1.5)

        assert stress["status"] == "available"
        assert stress["scenarios"]["market_-10pct"] == pytest.approx(-0.15)

    def test_stress_without_beta_is_unavailable(self) -> None:
        assert stress_scenarios(None) == {"status": "insufficient_data", "scenarios": {}}

    def test_correlation_matrix_detects_coincidence(self) -> None:
        returns = np.array([(-1 if i % 3 else 1) * (0.01 + i * 0.0002) for i in range(60)])
        histories = {
            "AAA": _history(returns),
            "BBB": _history(returns * 2, start=date(2024, 1, 1)),
        }

        matrix = correlation_matrix(histories)

        assert matrix["status"] == "available"
        assert matrix["pairs"]["AAA|BBB"] == pytest.approx(1.0, abs=1e-6)

    def test_concentration_hhi(self) -> None:
        assert concentration_hhi({"A": 1.0}) == pytest.approx(1.0)
        assert concentration_hhi({"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25}) == pytest.approx(0.25)
        assert concentration_hhi({"A": 0.0}) is None


class TestToolIntegration:
    def test_assess_risk_outputs_engine_metrics(self) -> None:
        benchmark = np.array([(-1 if i % 4 == 0 else 1) * (0.002 + i * 0.0005) for i in range(60)])
        result = assess_risk.invoke(
            {
                "market_data": {
                    "TEST": {
                        "symbol": "TEST",
                        "historical_data": _history(benchmark * 1.6),
                        "benchmark_historical_data": _history(benchmark),
                    }
                }
            }
        )["TEST"]

        metrics = result["metrics"]
        assert metrics["cvar_95"] is not None
        assert metrics["cvar_95"] <= metrics["var_95"]
        assert metrics["beta"] == pytest.approx(1.6, abs=1e-3)
        assert metrics["r_squared"] == pytest.approx(1.0, abs=1e-6)
        assert metrics["sortino"] is not None
        assert result["stress_scenarios"]["scenarios"]["market_-20pct"] == pytest.approx(-0.32)

    def test_assess_risk_without_benchmark_marks_relative_metrics_missing(self) -> None:
        result = assess_risk.invoke(
            {"market_data": {"TEST": {"symbol": "TEST", "historical_data": _history(np.linspace(-0.01, 0.02, 60))}}}
        )["TEST"]

        assert result["metrics"]["beta_status"] == "insufficient_data"
        assert result["metrics"]["alpha_annualized"] is None
        assert result["stress_scenarios"]["status"] == "insufficient_data"
