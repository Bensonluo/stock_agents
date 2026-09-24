"""Deflated Sharpe Ratio — pure math pins and walk-forward integration."""

import math

import numpy as np
import pandas as pd
import pytest

from app.backtest.dsr import BARS_PER_YEAR_SQRT, deflated_sharpe_ratio
from app.backtest.walkforward import walk_forward


def _returns(n: int = 120, mean: float = 0.001, seed: int = 7) -> list[float]:
    rng = np.random.default_rng(seed)
    return [float(r) for r in rng.normal(mean, 0.01, n)]


def _trials(seed: int = 11, n: int = 6) -> list[float]:
    """Annualized train Sharpes with dispersion (a real grid has spread)."""
    rng = np.random.default_rng(seed)
    return [float(s) for s in rng.normal(1.0, 0.6, n)]


class TestPureMath:
    def test_returns_probability_block_with_expected_keys(self) -> None:
        block = deflated_sharpe_ratio(_returns(), _trials(), n_configurations=6)
        assert block is not None and block["status"] == "ok"
        assert 0.0 <= block["dsr"] <= 1.0
        assert block["n_trials"] == 6
        assert block["oos_bars"] == 120
        for key in (
            "sharpe_annualized",
            "sr0_annualized",
            "trial_sharpe_std_annualized",
            "skew",
            "kurtosis",
        ):
            assert isinstance(block[key], float)

    def test_sharpe_matches_manual_computation(self) -> None:
        returns = _returns()
        block = deflated_sharpe_ratio(returns, _trials(), n_configurations=6)
        mean = sum(returns) / len(returns)
        std = math.sqrt(sum((r - mean) ** 2 for r in returns) / (len(returns) - 1))
        assert block["sharpe_annualized"] == pytest.approx(
            mean / std * BARS_PER_YEAR_SQRT, abs=1e-5
        )

    def test_more_configurations_deflate_harder(self) -> None:
        """The expected max of N noise trials grows with N: the same
        performance gets less credit the wider the search was."""
        small = deflated_sharpe_ratio(_returns(), _trials(), n_configurations=2)
        large = deflated_sharpe_ratio(_returns(), _trials(), n_configurations=100)
        assert small is not None and large is not None
        assert large["dsr"] < small["dsr"]
        assert large["sr0_annualized"] > small["sr0_annualized"]

    def test_better_oos_stream_gets_more_credit(self) -> None:
        weak = deflated_sharpe_ratio(_returns(mean=0.0), _trials(), n_configurations=6)
        strong = deflated_sharpe_ratio(_returns(mean=0.003), _trials(), n_configurations=6)
        assert weak is not None and strong is not None
        assert strong["dsr"] > weak["dsr"]

    def test_single_configuration_refuses(self) -> None:
        # N=1 means no selection happened — there is nothing to deflate.
        assert deflated_sharpe_ratio(_returns(), _trials(), n_configurations=1) is None

    def test_no_trial_dispersion_refuses(self) -> None:
        # Identical trials mean the grid carried no selection pressure.
        assert deflated_sharpe_ratio(_returns(), [0.5, 0.5, 0.5], n_configurations=3) is None

    def test_too_few_oos_bars_refuses(self) -> None:
        assert deflated_sharpe_ratio(_returns(19), _trials(), n_configurations=6) is None

    def test_zero_variance_stream_refuses(self) -> None:
        assert deflated_sharpe_ratio([0.001] * 50, _trials(), n_configurations=6) is None

    def test_non_finite_and_non_numeric_inputs_filtered(self) -> None:
        returns = _returns(40) + [float("nan"), float("inf"), "x"]  # type: ignore[list-item]
        block = deflated_sharpe_ratio(
            returns, _trials(3) + [None, float("nan")], n_configurations=6
        )
        assert block is not None and block["oos_bars"] == 40


def _ohlc(days: int, *, drift: float = 0.002, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = 100.0 * np.cumprod(1.0 + drift + rng.normal(0.0, 0.01, days))
    return pd.DataFrame(
        {
            "Open": np.concatenate(([100.0], closes[:-1])),
            "High": closes * 1.005,
            "Low": closes * 0.995,
            "Close": closes,
            "Volume": np.full(days, 1_000_000.0),
        },
        index=pd.bdate_range("2024-01-01", periods=days),
    )


class TestWalkForwardIntegration:
    def test_multi_combo_grid_emits_dsr(self) -> None:
        report = walk_forward(
            _ohlc(600),
            strategy="sma_crossover",
            param_grid={"sma_short": [5, 10, 20], "sma_long": [40, 60]},
            train_bars=150,
            test_bars=75,
        )
        block = report["aggregate"]["deflated_sharpe"]
        assert block is not None and block["status"] == "ok"
        # N is the grid size — the per-window search picks the best of 6.
        assert block["n_trials"] == 6
        assert 0.0 <= block["dsr"] <= 1.0
        # The pooled OOS stream spans every test segment.
        assert block["oos_bars"] > len(report["windows"]) * 10
        # Per-combo train Sharpes are recorded for every window.
        for window in report["windows"]:
            assert len(window["train_results"]) == 6
            assert all("sharpe" in entry for entry in window["train_results"])

    def test_single_combo_grid_refuses_dsr(self) -> None:
        report = walk_forward(
            _ohlc(400),
            strategy="sma_crossover",
            param_grid={"sma_short": [10], "sma_long": [40]},
            train_bars=150,
            test_bars=75,
        )
        assert report["aggregate"]["deflated_sharpe"] is None
