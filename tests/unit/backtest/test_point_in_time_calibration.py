"""Tests for point-in-time visibility and signal calibration (Phase 3 closeout)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.backtest import (
    calibrate_signals,
    latest_visible_value,
    stamp_visibility,
    visible_from,
    visible_values_at,
)
from app.backtest.engine import run_backtest

# ----------------------------------------------------------------------
# Point-in-time
# ----------------------------------------------------------------------


def _statement() -> dict:
    return {
        "dates": ["2024-12-31", "2023-12-31"],
        "data": {"Total Revenue": [120.0, 100.0]},
    }


class TestPointInTime:
    def test_visibility_requires_reporting_lag(self) -> None:
        assert visible_from("2024-12-31", lag_days=60) == date(2025, 3, 1)

        block = stamp_visibility(_statement(), lag_days=60)
        # 2024 is a leap year: 2023-12-31 + 60 days lands on Feb 29.
        assert block["visible_from"] == ["2025-03-01", "2024-02-29"]
        assert block["data"] == _statement()["data"]  # original block untouched

    def test_period_end_data_is_not_visible_at_period_end(self) -> None:
        # The newest period (2024-12-31) is invisible at that date; only the
        # year-older statement has cleared its 60-day lag.
        assert latest_visible_value(_statement(), "2024-12-31", "Total Revenue") == 100.0

    def test_latest_visible_value_respects_cutoff(self) -> None:
        assert latest_visible_value(_statement(), "2025-03-01", "Total Revenue") == 120.0
        assert latest_visible_value(_statement(), "2024-06-01", "Total Revenue") == 100.0
        assert latest_visible_value(_statement(), "2024-01-01", "Total Revenue") is None

    def test_visible_values_exclude_unfiled_periods(self) -> None:
        visible = visible_values_at(_statement(), "2024-06-01", "Total Revenue", lag_days=60)

        assert visible == [("2023-12-31", 100.0)]

    def test_negative_lag_rejected(self) -> None:
        with pytest.raises(ValueError):
            visible_from("2024-12-31", lag_days=-1)

    def test_agent_stamps_statements_with_visibility(self) -> None:
        dates = pd.to_datetime(["2024-12-31", "2023-12-31"])
        df = pd.DataFrame({"Total Revenue": [120.0, 100.0]}, index=dates).T

        from tests.unit.analysis.test_weekly_integration import (
            _load_agent_class,  # reuse stub loader
        )

        agent_class = _load_agent_class(
            "data_agent_under_test", "data_agent.py", "DataCollectionAgent"
        )
        agent = agent_class()
        block = agent._financial_statement_to_dict(df)

        assert block["visible_from"] == ["2025-03-01", "2024-02-29"]


# ----------------------------------------------------------------------
# Calibration
# ----------------------------------------------------------------------


def _ohlc(days: int = 500, *, drift: float = 0.001, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = [100.0]
    for _ in range(days - 1):
        closes.append(max(1.0, closes[-1] * (1 + drift + rng.normal(0, 0.01))))
    opens = [closes[0]] + closes[:-1]
    index = pd.bdate_range("2023-01-02", periods=days)
    return pd.DataFrame(
        {
            "Open": opens,
            "High": [max(o, c) for o, c in zip(opens, closes)],
            "Low": [min(o, c) for o, c in zip(opens, closes)],
            "Close": closes,
            "Volume": [1_000_000.0] * days,
        },
        index=index,
    )


class TestCalibration:
    def test_uptrend_entries_have_high_hit_rate(self) -> None:
        report = calibrate_signals(_ohlc(drift=0.002), strategy="sma_crossover", horizons=(20,))

        horizon = report["by_horizon"]["20"]
        assert horizon["events"] > 0
        assert horizon["hit_rate"] >= 0.5
        assert horizon["wilson_lower"] is not None
        assert horizon["wilson_lower"] <= horizon["hit_rate"]

    def test_no_benchmark_means_positive_return_is_a_hit(self) -> None:
        report = calibrate_signals(_ohlc(drift=0.003), strategy="buy_and_hold", horizons=(30,))

        horizon = report["by_horizon"]["30"]
        assert horizon["events"] == 1  # single entry, still measurable
        assert horizon["hit_rate"] == 1.0

    def test_by_year_breakdown_exposes_each_year(self) -> None:
        report = calibrate_signals(_ohlc(500), strategy="buy_and_hold", horizons=(20,))

        years = set(report["by_horizon"]["20"]["by_year"])
        assert years, "expected per-year buckets"

    def test_invalid_inputs_rejected(self) -> None:
        with pytest.raises(ValueError):
            calibrate_signals(_ohlc(), strategy="moon_shot")
        with pytest.raises(ValueError):
            calibrate_signals(_ohlc(), strategy="sma_crossover", horizons=(0,))

    def test_engine_normalizes_unsorted_and_duplicated_index(self) -> None:
        data = _ohlc(200)
        shuffled = data.iloc[::-1]
        duplicated = pd.concat([data, data.iloc[[-1]]])

        shuffled_result = run_backtest(shuffled, strategy="buy_and_hold")
        dup_result = run_backtest(duplicated, strategy="buy_and_hold")
        normal_result = run_backtest(data, strategy="buy_and_hold")

        assert shuffled_result.equity.iloc[-1] == pytest.approx(normal_result.equity.iloc[-1])
        assert dup_result.equity.iloc[-1] == pytest.approx(normal_result.equity.iloc[-1])
        assert len(dup_result.equity) == len(data)
