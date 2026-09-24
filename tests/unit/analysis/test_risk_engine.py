"""Specification tests for the deterministic risk engine."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from app.analysis.risk import (
    bootstrap_beta_ci,
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
            "beta_ci_95_low": None,
            "beta_ci_95_high": None,
            "alpha_annualized": None,
            "alpha_ci_95_low": None,
            "alpha_ci_95_high": None,
            "r_squared": None,
            "correlation": None,
        }

    def test_metrics_block_carries_the_beta_ci(self) -> None:
        benchmark = np.array([(-1 if i % 4 == 0 else 1) * (0.002 + i * 0.0005) for i in range(120)])
        stock = benchmark * 1.6

        metrics = relative_risk_metrics(stock, benchmark)

        assert metrics["beta_ci_95_low"] is not None
        assert metrics["beta_ci_95_high"] is not None
        assert metrics["beta_ci_95_low"] <= metrics["beta"] <= metrics["beta_ci_95_high"]

    def test_metrics_block_carries_the_alpha_ci(self) -> None:
        rng = np.random.default_rng(5)
        benchmark = rng.normal(0.0008, 0.01, size=250)
        stock = 1.2 * benchmark + rng.normal(0.0004, 0.006, size=250)

        metrics = relative_risk_metrics(stock, benchmark)

        assert metrics["alpha_ci_95_low"] is not None
        assert metrics["alpha_ci_95_high"] is not None
        assert (
            metrics["alpha_ci_95_low"] <= metrics["alpha_annualized"] <= metrics["alpha_ci_95_high"]
        )


class TestBootstrapBetaCi:
    """Percentile CI on the hedge ratio — beta is an estimate, not a fact."""

    @staticmethod
    def _noisy_pair(
        n: int, true_beta: float, noise_scale: float, seed: int
    ) -> tuple[np.ndarray, np.ndarray]:
        rng = np.random.default_rng(seed)
        benchmark = rng.normal(0.001, 0.01, size=n)
        stock = true_beta * benchmark + rng.normal(0, noise_scale, size=n)
        return stock, benchmark

    def test_interval_brackets_the_point_estimate(self) -> None:
        stock, benchmark = self._noisy_pair(250, 1.5, 0.008, seed=7)

        ci = bootstrap_beta_ci(stock, benchmark)
        beta = calculate_beta(stock, benchmark)

        assert ci is not None and beta is not None
        assert ci[0] <= beta <= ci[1]

    def test_deterministic_for_same_input(self) -> None:
        stock, benchmark = self._noisy_pair(80, 1.2, 0.01, seed=3)

        assert bootstrap_beta_ci(stock, benchmark) == bootstrap_beta_ci(stock, benchmark)

    def test_width_shrinks_with_more_aligned_data(self) -> None:
        # Same underlying relationship; 500 bars should pin beta tighter
        # than 40. Fixed seeds freeze both widths, so the pin is stable.
        short = self._noisy_pair(40, 1.0, 0.01, seed=11)
        long = self._noisy_pair(500, 1.0, 0.01, seed=11)

        ci_short = bootstrap_beta_ci(*short)
        ci_long = bootstrap_beta_ci(*long)

        assert ci_short is not None and ci_long is not None
        assert (ci_short[1] - ci_short[0]) > (ci_long[1] - ci_long[0])

    def test_zero_variance_benchmark_returns_none(self) -> None:
        stock = np.full(30, 0.01)

        assert bootstrap_beta_ci(stock, np.full(30, 0.005)) is None

    def test_below_min_observations_returns_none(self) -> None:
        rng = np.random.default_rng(1)
        bench = rng.normal(0, 0.01, size=10)

        assert bootstrap_beta_ci(bench * 1.3, bench) is None

    def test_calculate_beta_needs_min_observations(self) -> None:
        assert calculate_beta(np.full(10, 0.01), np.full(10, 0.01)) is None


class TestBootstrapRelativeCi:
    """Joint intervals — beta and alpha from ONE resampling, one uncertainty."""

    @staticmethod
    def _noisy_pair(
        n: int, true_beta: float, noise_scale: float, seed: int
    ) -> tuple[np.ndarray, np.ndarray]:
        rng = np.random.default_rng(seed)
        benchmark = rng.normal(0.001, 0.01, size=n)
        stock = true_beta * benchmark + rng.normal(0, noise_scale, size=n)
        return stock, benchmark

    def test_alpha_interval_brackets_the_point_estimate(self) -> None:
        from app.analysis.risk import bootstrap_relative_ci

        stock, benchmark = self._noisy_pair(250, 1.3, 0.008, seed=9)

        joint = bootstrap_relative_ci(stock, benchmark)
        metrics = relative_risk_metrics(stock, benchmark)

        assert joint is not None
        alpha_lo, alpha_hi = joint[1]
        assert alpha_lo <= metrics["alpha_annualized"] <= alpha_hi

    def test_beta_wrapper_matches_the_joint_beta_interval(self) -> None:
        from app.analysis.risk import bootstrap_relative_ci

        stock, benchmark = self._noisy_pair(120, 0.9, 0.012, seed=4)

        joint = bootstrap_relative_ci(stock, benchmark)

        assert bootstrap_beta_ci(stock, benchmark) == joint[0]

    def test_joint_output_is_deterministic(self) -> None:
        from app.analysis.risk import bootstrap_relative_ci

        stock, benchmark = self._noisy_pair(80, 1.1, 0.01, seed=2)

        assert bootstrap_relative_ci(stock, benchmark) == bootstrap_relative_ci(stock, benchmark)

    def test_alpha_interval_respects_the_risk_free_rate(self) -> None:
        from app.analysis.risk import bootstrap_relative_ci

        stock, benchmark = self._noisy_pair(200, 1.4, 0.009, seed=6)
        rf = 0.04

        raw = bootstrap_relative_ci(stock, benchmark)
        jensen = bootstrap_relative_ci(stock, benchmark, risk_free_rate_annual=rf)

        assert raw is not None and jensen is not None
        # Jensen's alpha = raw − rf·(1−β): with true beta near 1.4 the shift
        # is −rf·(−0.4) = +0.016 annualized, and the whole interval moves up,
        # not just a constant offset on the point estimate.
        assert jensen[1][1] > raw[1][1]


class TestJensenAlpha:
    """Jensen's alpha above a configurable risk-free rate."""

    def _pair(self, n: int = 40) -> tuple[np.ndarray, np.ndarray]:
        benchmark = np.array([0.01 if i % 2 == 0 else -0.01 for i in range(n)])
        stock = benchmark * 2 + 0.001  # beta 2, constant daily edge over beta
        return stock, benchmark

    def test_default_rf_zero_is_bit_for_bit_old_alpha(self) -> None:
        stock, benchmark = self._pair()

        assert relative_risk_metrics(stock, benchmark) == relative_risk_metrics(
            stock, benchmark, risk_free_rate_annual=0.0
        )

    def test_hand_computed_jensen_alpha(self) -> None:
        stock, benchmark = self._pair()

        metrics = relative_risk_metrics(stock, benchmark, risk_free_rate_annual=0.04)

        # Raw alpha = 0.001 * 252 = 0.252; Jensen = 0.252 - 0.04 * (1 - 2) = 0.292
        assert metrics["beta"] == pytest.approx(2.0, abs=1e-6)
        assert metrics["alpha_annualized"] == pytest.approx(0.292, abs=1e-4)

    def test_beta_one_leaves_alpha_rf_invariant(self) -> None:
        _stock, benchmark = self._pair()
        beta_one = benchmark + 0.0005

        raw = relative_risk_metrics(beta_one, benchmark)
        jensen = relative_risk_metrics(beta_one, benchmark, risk_free_rate_annual=0.04)

        assert raw["beta"] == pytest.approx(1.0, abs=1e-6)
        assert jensen["alpha_annualized"] == pytest.approx(raw["alpha_annualized"], abs=1e-6)

    def test_assess_symbol_wires_settings_rf(self, monkeypatch) -> None:
        from app.tools.risk import assessment

        class _Settings:
            risk_free_rate_annual = 0.04
            min_adv_usd = 2_000_000
            min_adv_cny = 20_000_000

        monkeypatch.setattr(assessment, "get_settings", lambda: _Settings())
        stock, benchmark = self._pair()
        result = assessment._assess_symbol(
            "TEST",
            {
                "historical_data": _history(stock),
                "benchmark_historical_data": _history(benchmark),
            },
        )

        assert result["metrics"]["alpha_annualized"] == pytest.approx(0.292, abs=1e-4)
        assert result["metrics"]["alpha_risk_free_rate_annual"] == 0.04


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
        assert concentration_hhi({"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25}) == pytest.approx(
            0.25
        )
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
            {
                "market_data": {
                    "TEST": {
                        "symbol": "TEST",
                        "historical_data": _history(np.linspace(-0.01, 0.02, 60)),
                    }
                }
            }
        )["TEST"]

        assert result["metrics"]["beta_status"] == "insufficient_data"
        assert result["metrics"]["alpha_annualized"] is None
        assert result["stress_scenarios"]["status"] == "insufficient_data"
