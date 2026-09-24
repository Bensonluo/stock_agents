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
