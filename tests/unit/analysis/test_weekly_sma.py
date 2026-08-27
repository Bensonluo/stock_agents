"""Specification tests for the deterministic weekly SMA engine (V2 plan §3.2.D)."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from app.analysis.technical import WEEKLY_SMA_WINDOWS, resample_weekly, weekly_sma_pack
from app.domain.schemas import MetricQuality, QualityGateVerdict

AS_OF = datetime(2026, 8, 26, tzinfo=UTC)


def _daily_history(closes: list[float], *, start: str = "2023-08-01", volume_step: float = 0.0) -> dict:
    """Wrap a close series into a daily history on business days."""
    dates = [d.isoformat() for d in pd.bdate_range(start, periods=len(closes))]
    volumes = [1_000_000 + volume_step * i for i in range(len(closes))]
    return {"dates": dates, "close": closes, "volume": volumes}


def _uptrend_days(weeks: int) -> dict:
    """Strictly increasing exponential closes on business days (~5 per week)."""
    days = weeks * 5
    closes = [100.0 * (1.002**i) for i in range(days)]
    return _daily_history(closes)


def _assert_no_nan(node) -> None:
    if isinstance(node, dict):
        for value in node.values():
            _assert_no_nan(value)
    elif isinstance(node, (list, tuple)):
        for value in node:
            _assert_no_nan(value)
    elif isinstance(node, float):
        assert not math.isnan(node), "NaN leaked into the SMA pack"


class TestResampleWeekly:
    def test_weekly_close_is_last_daily_close_and_volume_sums(self) -> None:
        dates = [d.isoformat() for d in pd.bdate_range("2026-07-06", periods=10)]
        closes = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0]
        volumes = [100.0] * 10

        weekly = resample_weekly(dates, closes, volumes)

        assert list(weekly["close"]) == [14.0, 19.0]
        assert list(weekly["volume"]) == [500.0, 500.0]
        assert weekly.index.strftime("%a").tolist() == ["Fri", "Fri"]

    def test_duplicate_timestamps_keep_last_close(self) -> None:
        dates = ["2026-07-06", "2026-07-06", "2026-07-07"]
        closes = [10.0, 11.0, 12.0]

        weekly = resample_weekly(dates, closes)

        assert list(weekly["close"]) == [12.0]


class TestWeeklySmaPack:
    def test_three_year_uptrend_is_fully_available_and_bullish(self) -> None:
        pack = weekly_sma_pack(_uptrend_days(160), symbol="AAPL", source="yfinance")

        assert pack["status"] == "available"
        assert pack["alignment"]["state"] == "bullish"
        assert pack["data_quality"].verdict is QualityGateVerdict.PASS
        for detail in pack["sma"].values():
            assert detail["warm_up_met"] is True
            assert detail["value"] > 0
            assert detail["distance_pct"] > 0  # price above every SMA in an uptrend
            assert detail["slope_4w_pct"] > 0
            assert detail["slope_12w_pct"] > 0
            assert detail["weeks_above"] >= 1

    def test_alignment_duration_spans_every_week_where_all_lines_exist(self) -> None:
        pack = weekly_sma_pack(_uptrend_days(160), symbol="AAPL")

        # SMA60 first exists at week 60 (index 59); every week after is bullish.
        assert pack["alignment"]["weeks_in_state"] == pack["weekly_bars"] - 59

    def test_downtrend_is_bearish_with_price_below_every_line(self) -> None:
        days = 160 * 5
        closes = [200.0 * (0.998**i) for i in range(days)]
        pack = weekly_sma_pack(_daily_history(closes), symbol="TSLA")

        assert pack["alignment"]["state"] == "bearish"
        for detail in pack["sma"].values():
            assert detail["distance_pct"] < 0
            assert detail["slope_4w_pct"] < 0

    def test_short_history_degrades_long_windows_instead_of_guessing(self) -> None:
        # ~30 weeks of data: 5/10/20 warm up, 40/60 cannot.
        closes = [100.0 * (1.002**i) for i in range(30 * 5)]
        pack = weekly_sma_pack(_daily_history(closes), symbol="AAPL")

        assert pack["status"] == "partial"
        assert pack["sma"]["5"]["warm_up_met"] is True
        assert pack["sma"]["40"]["warm_up_met"] is False
        assert pack["sma"]["40"]["value"] is None
        assert pack["sma"]["40"]["status"] == "insufficient_data"
        assert pack["data_quality"].coverage["AAPL"] == pytest.approx(3 / 5)
        assert pack["data_quality"].verdict is QualityGateVerdict.DEGRADED

    def test_alignment_requires_all_five_lines(self) -> None:
        closes = [100.0 * (1.002**i) for i in range(30 * 5)]
        pack = weekly_sma_pack(_daily_history(closes), symbol="AAPL")

        assert pack["alignment"]["state"] == "insufficient_data"

    def test_empty_or_malformed_history_is_rejected(self) -> None:
        for history in ({}, {"dates": [], "close": []}, {"dates": ["2026-01-05"], "close": []}):
            pack = weekly_sma_pack(history, symbol="AAPL", as_of=AS_OF)

            assert pack["status"] == "insufficient_data"
            assert pack["reason"]
            assert pack["evidence"] == []

    def test_never_leaks_nan(self) -> None:
        closes = [100.0 * (1.002**i) for i in range(30 * 5)]
        _assert_no_nan(weekly_sma_pack(_daily_history(closes), symbol="AAPL"))


class TestEvidence:
    def test_evidence_ids_are_canonical_and_stamped_with_as_of(self) -> None:
        pack = weekly_sma_pack(_uptrend_days(160), symbol="AAPL", as_of=AS_OF, source="yfinance")

        by_name = {e.name: e for e in pack["evidence"]}
        sma20 = by_name["sma_weekly_20"]
        assert sma20.metric_id == "AAPL.technical.sma_weekly_20.2026-08-26"
        assert sma20.unit == "USD"
        assert sma20.source == "yfinance"
        assert sma20.formula == "mean(weekly_close, 20)"
        assert sma20.params == {"window": 20, "frequency": "1wk"}
        assert sma20.sample_count == pack["weekly_bars"] - 19
        assert sma20.quality is MetricQuality.VERIFIED

    def test_insufficient_windows_emit_explicit_missing_evidence(self) -> None:
        closes = [100.0 * (1.002**i) for i in range(30 * 5)]
        pack = weekly_sma_pack(_daily_history(closes), symbol="AAPL")

        missing = [e for e in pack["evidence"] if e.name == "sma_weekly_60"]
        assert len(missing) == 1
        assert missing[0].value is None
        assert missing[0].quality is MetricQuality.INSUFFICIENT_DATA

    def test_currency_unit_is_propagated(self) -> None:
        pack = weekly_sma_pack(_uptrend_days(160), symbol="600519", currency="CNY")

        price_evidence_units = {
            e.unit
            for e in pack["evidence"]
            if e.name in {f"sma_weekly_{w}" for w in WEEKLY_SMA_WINDOWS}
        }
        assert price_evidence_units == {"CNY"}


class TestCrosses:
    def test_uptrend_reports_no_cross_and_fast_above(self) -> None:
        pack = weekly_sma_pack(_uptrend_days(160), symbol="AAPL")

        fast_vs_mid = pack["crosses"]["5_vs_10"]
        assert fast_vs_mid == {"status": "no_cross_observed", "relation": "fast_above"}

    def test_reversal_produces_recent_golden_cross(self) -> None:
        decline = [200.0 * (0.995**i) for i in range(110 * 5)]
        trough = decline[-1]
        rise = [trough * (1.006**i) for i in range(30 * 5)]
        pack = weekly_sma_pack(
            _daily_history(decline + rise, volume_step=5_000.0), symbol="NVDA"
        )

        cross = pack["crosses"]["5_vs_10"]
        assert cross["status"] == "observed"
        assert cross["direction"] == "golden"
        assert cross["return_since_pct"] > 0
        parsed = date.fromisoformat(cross["cross_date"])
        assert parsed <= date.today() + timedelta(days=1)


class TestReproducibility:
    def test_same_snapshot_yields_identical_pack(self) -> None:
        history = _uptrend_days(160)

        first = weekly_sma_pack(history, symbol="AAPL", as_of=AS_OF)
        second = weekly_sma_pack(history, symbol="AAPL", as_of=AS_OF)

        assert first == second
