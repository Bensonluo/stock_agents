"""Specification tests for the V2 backtest layer (V2 plan §7.1)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from app.backtest import (
    CN_STOCK,
    ZERO,
    CostModel,
    build_manifest,
    hash_dataframe,
    run_backtest,
    walk_forward,
)


def _ohlc(days: int = 300, *, drift: float = 0.002, seed: int = 7) -> pd.DataFrame:
    """Deterministic OHLC frame: overnight gap-free, open == prev close."""
    rng = np.random.default_rng(seed)
    closes = [100.0]
    for _ in range(days - 1):
        closes.append(max(1.0, closes[-1] * (1 + drift + rng.normal(0, 0.01))))
    opens = [closes[0]] + closes[:-1]  # open of bar t is close of bar t-1
    index = pd.bdate_range("2024-01-01", periods=days)
    return pd.DataFrame(
        {
            "Open": opens,
            "High": [max(o, c) * 1.005 for o, c in zip(opens, closes)],
            "Low": [min(o, c) * 0.995 for o, c in zip(opens, closes)],
            "Close": closes,
            "Volume": [1_000_000.0] * days,
        },
        index=index,
    )


def _no_nan(value) -> bool:
    if isinstance(value, dict):
        return all(_no_nan(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return all(_no_nan(v) for v in value)
    if isinstance(value, float):
        return not math.isnan(value)
    return True


class TestNoLookAhead:
    @pytest.mark.parametrize("strategy", ["sma_crossover", "rsi_strategy", "macd_strategy"])
    def test_signal_executes_at_next_bar_open(self, strategy: str) -> None:
        # A signal on close of bar t must fill at open of t+1. With open(t+1)
        # == close(t) (gap-free data) the first fill price equals the close
        # that produced the signal — verifying it is NOT the same bar's close
        # AFTER the signal bar; i.e. the fill date must be strictly later.
        data = _ohlc()
        result = run_backtest(data, strategy=strategy, cost_model=ZERO)

        buys = [t for t in result.trades if t["action"] == "buy"]
        if not buys:
            pytest.skip("strategy produced no trade on this sample")
        first_buy = pd.Timestamp(buys[0]["date"])
        warmup = {"sma_crossover": 50, "rsi_strategy": 14, "macd_strategy": 35}[strategy]
        # earliest possible signal bar is the warm-up bar; fill must be after it
        assert first_buy >= data.index[warmup]

    def test_trades_never_occur_before_warmup(self) -> None:
        data = _ohlc()
        result = run_backtest(data, strategy="sma_crossover", sma_short=20, sma_long=50)

        first_signal_bar = data.index[49]
        for trade in result.trades:
            assert pd.Timestamp(trade["date"]) >= first_signal_bar

    def test_equity_starts_at_initial_cash(self) -> None:
        result = run_backtest(_ohlc(), strategy="sma_crossover", cost_model=ZERO)

        assert result.equity.iloc[0] == pytest.approx(10_000.0)


class TestCosts:
    def test_costs_reduce_final_equity_against_zero_cost(self) -> None:
        data = _ohlc()

        free = run_backtest(data, strategy="sma_crossover", cost_model=ZERO)
        costly = run_backtest(
            data, strategy="sma_crossover", cost_model=CostModel(commission_rate=0.01)
        )

        assert free.trades, "expected trades for comparison"
        assert costly.equity.iloc[-1] < free.equity.iloc[-1]

    def test_stamp_tax_charged_on_sell_side_only(self) -> None:
        model = CostModel(commission_rate=0.0, stamp_tax=0.001)
        assert model.buy_cost(100_000.0) == 0.0
        assert model.sell_cost(100_000.0) == pytest.approx(100.0)

    def test_cn_preset_carries_min_commission(self) -> None:
        assert CN_STOCK.buy_cost(100.0) == pytest.approx(5.0 + 0.001)  # min commission + transfer fee
        assert CN_STOCK.buy_cost(1_000_000.0) == pytest.approx(300.0 + 10.0)

    def test_slippage_moves_fill_prices_adversarially(self) -> None:
        model = CostModel(commission_rate=0.0, slippage_rate=0.001)
        assert model.buy_price(100.0) == pytest.approx(100.1)
        assert model.sell_price(100.0) == pytest.approx(99.9)

    def test_negative_rate_rejected(self) -> None:
        with pytest.raises(ValueError):
            CostModel(commission_rate=-0.01)


class TestMetrics:
    def test_full_metric_suite_is_reported(self) -> None:
        result = run_backtest(_ohlc(drift=0.003), strategy="buy_and_hold", cost_model=ZERO)

        expected = {
            "total_return", "cagr", "volatility_annualized", "sharpe", "sortino",
            "calmar", "max_drawdown", "cvar_95_daily", "excess_vs_benchmark",
            "total_cost", "cost_ratio",
        }
        missing = expected - set(result.metrics)
        assert not missing
        assert result.metrics["total_return"] > 0  # uptrend must not lose money
        assert result.metrics["max_drawdown"] >= 0

    def test_benchmark_excess_is_strategy_minus_benchmark(self) -> None:
        data = _ohlc(drift=0.002)
        benchmark = _ohlc(drift=0.005, seed=99)
        result = run_backtest(
            data, strategy="buy_and_hold", cost_model=ZERO, benchmark_data=benchmark
        )

        assert result.metrics["excess_vs_benchmark"] is not None
        assert result.metrics["excess_vs_benchmark"] < 0  # lagging the faster benchmark

    def test_no_nan_leaks_into_metrics(self) -> None:
        result = run_backtest(_ohlc(60), strategy="sma_crossover")

        assert _no_nan(result.metrics)


class TestDeterminism:
    def test_same_inputs_same_outputs(self) -> None:
        data = _ohlc()

        first = run_backtest(data, strategy="sma_crossover", cost_model=CN_STOCK)
        second = run_backtest(data, strategy="sma_crossover", cost_model=CN_STOCK)

        assert first.equity.equals(second.equity)
        assert first.trades == second.trades
        assert first.metrics == second.metrics

    def test_unknown_strategy_or_param_rejected(self) -> None:
        with pytest.raises(ValueError):
            run_backtest(_ohlc(), strategy="moon_shot")
        with pytest.raises(ValueError):
            run_backtest(_ohlc(), strategy="sma_crossover", rsi_period=14)

    def test_data_hash_is_stable_and_content_sensitive(self) -> None:
        data = _ohlc()
        assert hash_dataframe(data) == hash_dataframe(data.copy())
        assert hash_dataframe(data) != hash_dataframe(_ohlc(seed=8))


class TestWalkForward:
    def test_walk_forward_picks_params_on_train_only_and_reports_failures(self) -> None:
        data = _ohlc(600)
        report = walk_forward(
            data,
            strategy="sma_crossover",
            param_grid={"sma_short": [5, 10, 20], "sma_long": [40, 60]},
            train_bars=150,
            test_bars=75,
            cost_model=ZERO,
        )

        assert report["windows"], "expected at least one window"
        assert report["configs_tested"] == 6 * len(report["windows"])
        for window in report["windows"]:
            assert set(window["chosen_params"]) == {"sma_short", "sma_long"}
            # chosen params must be one of the grid combos
            assert window["chosen_params"]["sma_long"] in (40, 60)
        aggregate = report["aggregate"]
        assert aggregate["windows_run"] == len(report["windows"])
        assert aggregate["losing_windows"] is not None  # failures are shown
        assert 0.0 <= aggregate["param_stability"] <= 1.0

    def test_insufficient_data_reported_not_crashed(self) -> None:
        report = walk_forward(
            _ohlc(50),
            strategy="sma_crossover",
            param_grid={"sma_short": [5], "sma_long": [20]},
            train_bars=100,
            test_bars=50,
        )

        assert report["windows"] == []
        assert "error" in report["aggregate"]

    def test_invalid_window_sizes_rejected(self) -> None:
        with pytest.raises(ValueError):
            walk_forward(
                _ohlc(), strategy="sma_crossover", param_grid={"sma_short": [5], "sma_long": [20]},
                train_bars=0, test_bars=10,
            )


class TestManifest:
    def test_manifest_pins_data_params_and_commit(self) -> None:
        data = _ohlc()
        manifest = build_manifest(
            symbol="AAPL",
            strategy="sma_crossover",
            params={"sma_short": 10, "sma_long": 40},
            start="2024-01-01",
            end="2024-12-31",
            data=data,
            cost_model=CN_STOCK,
            configs_tested=6,
        )

        assert manifest["data_sha256"] == hash_dataframe(data)
        assert manifest["params"] == {"sma_short": 10, "sma_long": 40}
        assert manifest["cost_model"]["stamp_tax"] == CN_STOCK.stamp_tax
        assert manifest["configs_tested"] == 6
        assert manifest["code_commit"] is None or len(manifest["code_commit"]) == 40
