"""Specification tests for the canonical daily technical engine."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pandas as pd
import pytest

from app.analysis.technical import (
    analyze_daily,
    calculate_indicators,
    generate_signals,
    to_dataframe,
)


def _daily(days: int = 800) -> dict[str, list]:
    closes = [100.0 * (1.002**i) for i in range(days)]
    return {
        "dates": [d.isoformat() for d in pd.bdate_range("2023-08-01", periods=days)],
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
        "volume": [1_000_000.0] * days,
    }


def _assert_no_nan(node) -> None:
    if isinstance(node, dict):
        for value in node.values():
            _assert_no_nan(value)
    elif isinstance(node, list | tuple):
        for value in node:
            _assert_no_nan(value)
    elif isinstance(node, float):
        assert not math.isnan(node), "NaN leaked into daily analysis"


class TestAnalyzeDaily:
    def test_full_history_has_all_moving_averages_and_bullish_signals(self) -> None:
        result = analyze_daily(_daily(), symbol="AAPL", source="test")

        assert result["status"] == "available"
        assert result["indicators"]["sma_200"] is not None
        assert result["signals"]["trend"] in ("bullish", "strong_bullish")
        assert result["sentiment"]["score"] > 0
        assert result["signals"]["volume"] in ("normal", "above_average", "high")
        assert result["current_price"] == pytest.approx(100.0 * 1.002**799, rel=1e-6)

    def test_missing_sma_windows_are_none_not_nan(self) -> None:
        result = analyze_daily(_daily(30), symbol="AAPL")

        assert result["indicators"]["sma_20"] is not None
        assert result["indicators"]["sma_50"] is None
        assert result["indicators"]["sma_200"] is None

    def test_short_history_is_explicit_insufficient_data(self) -> None:
        result = analyze_daily(_daily(15), symbol="AAPL")

        assert result["status"] == "insufficient_data"
        assert "15" in result["reason"]
        assert result["signals"] == {}

    def test_evidence_is_json_safe_with_canonical_ids(self) -> None:
        result = analyze_daily(_daily(), symbol="AAPL", source="test")

        by_name = {item["name"]: item for item in result["evidence"]}
        assert by_name["sma_daily_200"]["metric_id"].startswith("AAPL.technical.sma_daily_200.")
        assert by_name["rsi_daily_14"]["unit"] == "index"
        assert by_name["atr_pct_daily_14"]["unit"] == "percent"
        assert all(isinstance(item, dict) for item in result["evidence"])

    def test_no_nan_leaks_anywhere(self) -> None:
        _assert_no_nan(analyze_daily(_daily(45), symbol="AAPL"))

    def test_bollinger_violation_sets_signal(self) -> None:
        closes = [100.0] * 60
        history = _daily(60)
        history["close"] = closes
        history["close"][-1] = 140.0  # spike far above the flat band

        result = analyze_daily(history, symbol="STABLE")

        assert result["signals"]["bollinger"] == "overbought"


class TestDeduplication:
    def test_legacy_aliases_point_at_engine(self) -> None:
        from app.tools.analysis.technical import (
            _calculate_indicators,
            _calculate_sentiment,
            _find_support_resistance,
            _generate_signals,
            _to_dataframe,
        )

        assert _to_dataframe is to_dataframe
        assert _calculate_indicators is calculate_indicators
        assert _generate_signals is generate_signals
        assert (
            _find_support_resistance
            is __import__(
                "app.analysis.technical", fromlist=["find_support_resistance"]
            ).find_support_resistance
        )
        assert (
            _calculate_sentiment
            is __import__(
                "app.analysis.technical", fromlist=["calculate_sentiment"]
            ).calculate_sentiment
        )

    def test_tool_and_engine_agree_on_same_history(self) -> None:
        from app.tools.analysis.technical import analyze_technical

        history = _daily()
        tool_result = analyze_technical.invoke(
            {
                "market_data": {
                    "AAPL": {"symbol": "AAPL", "current_price": None, "historical_data": history}
                }
            }
        )

        direct = analyze_daily(history, symbol="AAPL", source="market_data_history")
        assert tool_result["AAPL"]["indicators"] == direct["indicators"]
        assert tool_result["AAPL"]["signals"] == direct["signals"]
        assert tool_result["AAPL"]["sentiment"] == direct["sentiment"]


class TestFreshness:
    """Stale bars (suspension, broken feed) must be labeled, not silent."""

    def _hist_ending(self, days_before_today: int, bars: int = 60) -> dict[str, list]:
        end = pd.Timestamp(datetime.now(UTC).date()) - pd.Timedelta(days=days_before_today)
        closes = [100.0 * (1.002**i) for i in range(bars)]
        return {
            "dates": [d.isoformat() for d in pd.bdate_range(end=end, periods=bars)],
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1_000_000.0] * bars,
        }

    def test_current_bars_not_stale(self) -> None:
        result = analyze_daily(self._hist_ending(0), symbol="AAPL")
        freshness = result["freshness"]

        assert freshness["stale"] is False
        assert freshness["age_days"] <= 4  # weekend + holiday slack
        assert freshness["as_of"] == result["as_of"][:10]

    def test_old_bars_flagged_stale(self) -> None:
        result = analyze_daily(self._hist_ending(60), symbol="AAPL")

        assert result["freshness"]["stale"] is True
        assert result["freshness"]["age_days"] >= 55

    def test_staleness_annotation_changes_no_signals(self) -> None:
        fresh = analyze_daily(self._hist_ending(0), symbol="AAPL")
        stale = analyze_daily(self._hist_ending(60), symbol="AAPL")

        assert stale["status"] == "available"
        assert stale["signals"] == fresh["signals"]
        assert stale["sentiment"] == fresh["sentiment"]

    def test_boundary_exactly_14_days_is_fresh(self) -> None:
        from app.analysis.technical import assess_freshness

        now = datetime(2026, 9, 24, tzinfo=UTC)
        at_limit = assess_freshness(datetime(2026, 9, 10, tzinfo=UTC), now=now)
        over_limit = assess_freshness(datetime(2026, 9, 9, tzinfo=UTC), now=now)

        assert at_limit["stale"] is False
        assert over_limit["stale"] is True


class TestReportFreshness:
    """The report's technical section must surface the stale flag."""

    def _section(self, analysis: dict) -> dict:
        from app.services.report_service import ReportService

        return ReportService._technical({"symbols": ["X"], "technical_analysis": {"X": analysis}})

    def test_stale_flag_reaches_report_section(self) -> None:
        section = self._section(
            {
                "signals": {},
                "sentiment": {"score": 0},
                "freshness": {"as_of": "2026-01-10", "age_days": 250, "stale": True},
            }
        )

        assert section["by_symbol"]["X"]["freshness"]["stale"] is True

    def test_missing_freshness_omits_key(self) -> None:
        section = self._section({"signals": {}, "sentiment": {"score": 0}})

        assert "freshness" not in section["by_symbol"]["X"]


class TestWilderRsi:
    """RSI(14) uses Wilder smoothing — SMA seed then exponential recursion —
    the definition every charting platform shows. These tests pin the seed,
    the recursion, and the edge behavior a data-driven engine must survive."""

    @staticmethod
    def _rsi(closes: list[float], period: int = 14) -> float | None:
        from app.analysis.technical.daily import _rsi as impl

        return impl(pd.Series(closes, dtype=float), period=period)

    def test_hand_computed_wilder_example(self) -> None:
        # deltas [1, 1, 1, -1, -1], period 3:
        # seed avg_gain=1.0, avg_loss=0
        # step -1: avg_gain=(1*2+0)/3=2/3, avg_loss=(0*2+1)/3=1/3
        # step -1: avg_gain=(2/3*2)/3=4/9, avg_loss=(1/3*2+1)/3=5/9
        # RS=(4/9)/(5/9)=0.8 -> RSI=100-100/1.8=44.4444
        assert self._rsi([10, 11, 12, 13, 12, 11], period=3) == pytest.approx(44.4444, abs=1e-3)

    def test_matches_ewm_reference_implementation(self) -> None:
        # Wilder smoothing is an EMA with alpha=1/period seeded by the SMA of
        # the first `period` changes — an independent vectorized formulation
        # must agree with the loop implementation to the last bar.
        closes = [
            100 + 2 * math.sin(i / 5) + (i % 7) * 0.3 - 0.9 for i in range(120)
        ]  # jumpy mix of gains and losses
        period = 14

        delta = pd.Series(closes).diff().dropna()
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)
        seed_gain = float(gain.iloc[:period].mean())
        seed_loss = float(loss.iloc[:period].mean())
        padded_gain = pd.concat([pd.Series([seed_gain]), gain.iloc[period:]])
        padded_loss = pd.concat([pd.Series([seed_loss]), loss.iloc[period:]])
        ref_gain = padded_gain.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
        ref_loss = padded_loss.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
        expected = 100 - 100 / (1 + ref_gain / ref_loss)

        # The engine rounds to 4 decimals; the reference agrees to that digit.
        assert self._rsi(closes, period=period) == pytest.approx(float(expected), abs=1e-4)

    def test_monotone_up_is_100(self) -> None:
        assert self._rsi([100.0 * (1.002**i) for i in range(60)]) == 100.0

    def test_flat_series_is_none(self) -> None:
        # A flat tape has no momentum signal — not a fabricated neutral 50.
        assert self._rsi([50.0] * 60) is None

    def test_warmup_guard(self) -> None:
        assert self._rsi([1.0, 2.0, 3.0, 4.0, 5.0], period=14) is None
        # period+1 closes = seed-only RSI, the minimum viable value.
        assert self._rsi([10, 11, 12, 13, 12], period=4) is not None

    def test_smoothing_differs_from_simple_rolling_mean(self) -> None:
        # The upgrade's whole point: on a mixed-gains-and-losses tape the
        # exponentially-weighted averages keep older bars in the denominator,
        # so Wilder RSI is a different (steadier) number than the old simple
        # 14-bar rolling mean on identical closes.
        closes = [100 + 2 * math.sin(i / 5) + (i % 7) * 0.3 - 0.9 for i in range(120)]

        delta = pd.Series(closes).diff().dropna()
        simple = 100 - 100 / (
            1
            + delta.clip(lower=0).rolling(14).mean().iloc[-1]
            / (-delta.clip(upper=0)).rolling(14).mean().iloc[-1]
        )
        wilder = self._rsi(closes, period=14)

        assert 0 <= wilder <= 100
        assert abs(wilder - float(simple)) > 0.5
