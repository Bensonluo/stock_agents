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


class TestWilderAtr:
    """ATR(14) uses Wilder smoothing — SMA seed then exponential recursion —
    the definition every charting platform shows (TradingView ta.atr is RMA).
    ATR feeds the 2xATR stop-distance position sizing, so its smoothing must
    match what a user's chart corroborates."""

    @staticmethod
    def _atr_frame(highs: list[float], lows: list[float], closes: list[float]) -> pd.DataFrame:
        from app.analysis.technical.daily import _atr as impl

        return impl(
            pd.DataFrame({"high": highs, "low": lows, "close": closes}, dtype=float), period=3
        )

    def test_hand_computed_wilder_example(self) -> None:
        # TRs [1.0, 1.0, 2.0, 1.5, 2.0], period 3 (prev-close terms dominate
        # rows 1/2/4: |11.0-10.0|, |12.5-10.5|, |13.0-11.0|):
        # seed = mean(1.0, 1.0, 2.0) = 4/3
        # step 1.5: (4/3*2 + 1.5)/3 = 1.3889
        # step 2.0: (1.3889*2 + 2.0)/3 = 1.5926
        atr = self._atr_frame(
            highs=[10.5, 11.0, 12.5, 12.0, 13.0],
            lows=[9.5, 10.2, 11.0, 10.5, 11.8],
            closes=[10.0, 10.5, 11.5, 11.0, 12.0],
        )
        assert atr == pytest.approx(1.592593, abs=1e-6)

    def test_matches_ewm_reference_implementation(self) -> None:
        # Wilder smoothing is an EMA with alpha=1/period seeded by the SMA of
        # the first `period` true ranges — an independent vectorized
        # formulation must agree with the loop implementation.
        closes = [100 + 2 * math.sin(i / 5) + (i % 7) * 0.3 - 0.9 for i in range(120)]
        highs = [c + 0.5 + (i % 5) * 0.1 for i, c in enumerate(closes)]
        lows = [c - 0.4 - (i % 3) * 0.15 for i, c in enumerate(closes)]
        period = 14

        close_s = pd.Series(closes)
        tr = pd.concat(
            [
                pd.Series(highs) - pd.Series(lows),
                (pd.Series(highs) - close_s.shift()).abs(),
                (pd.Series(lows) - close_s.shift()).abs(),
            ],
            axis=1,
        ).max(axis=1)
        seed = float(tr.iloc[:period].mean())
        padded = pd.concat([pd.Series([seed]), tr.iloc[period:]])
        ref = padded.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]

        from app.analysis.technical.daily import _atr as impl

        df = pd.DataFrame({"high": highs, "low": lows, "close": closes})
        # The engine rounds to 6 decimals; the reference agrees to that digit.
        assert impl(df, period=period) == pytest.approx(float(ref), abs=1e-6)

    def test_first_bar_true_range_is_high_low(self) -> None:
        # Row 0 has no previous close; its TR is the high-low range
        # (Wilder's own seeding bar), not a skipped/NaN bar.
        atr = self._atr_frame(
            highs=[11.0, 11.0, 11.0, 11.0],
            lows=[9.0, 10.0, 10.0, 10.0],
            closes=[10.0, 10.0, 10.0, 10.0],
        )
        # TRs [2.0, 1.0, 1.0, 1.0], period 3: seed 4/3 -> (4/3*2+1)/3 = 1.2222
        assert atr == pytest.approx(1.222222, abs=1e-6)

    def test_warmup_guard(self) -> None:
        from app.analysis.technical.daily import _atr as impl

        three = pd.DataFrame(
            {"high": [11.0] * 3, "low": [9.0] * 3, "close": [10.0] * 3}, dtype=float
        )
        assert impl(three, period=3) is None
        # period+1 bars = seed + one smoothing step, the minimum viable ATR.
        four = pd.DataFrame(
            {"high": [11.0] * 4, "low": [9.0] * 4, "close": [10.0] * 4}, dtype=float
        )
        assert impl(four, period=3) is not None

    def test_smoothing_differs_from_simple_rolling_mean(self) -> None:
        # The upgrade's whole point: a volatility burst ~25 bars back has
        # already fallen out of the simple 14-bar rolling mean but Wilder's
        # exponential weights still carry it — the two formulas disagree on
        # identical bars.
        closes = [100 + 2 * math.sin(i / 5) + (i % 7) * 0.3 - 0.9 for i in range(120)]
        spread = [2.5 if 80 <= i <= 92 else 0.5 for i in range(120)]
        highs = [c + s for c, s in zip(closes, spread)]
        lows = [c - s for c, s in zip(closes, spread)]
        period = 14

        close_s = pd.Series(closes)
        tr = pd.concat(
            [
                pd.Series(highs) - pd.Series(lows),
                (pd.Series(highs) - close_s.shift()).abs(),
                (pd.Series(lows) - close_s.shift()).abs(),
            ],
            axis=1,
        ).max(axis=1)
        simple = float(tr.rolling(period).mean().iloc[-1])

        from app.analysis.technical.daily import _atr as impl

        wilder = impl(pd.DataFrame({"high": highs, "low": lows, "close": closes}), period=period)

        assert wilder is not None
        # simple forgets the burst (~1.21), Wilder still tastes it (~1.57)
        assert abs(wilder - simple) > 0.1


class TestWilderAdx:
    """ADX(14) — the third Wilder-smoothed indicator. The MA-structure trend
    label carries direction only; ADX grades the trend's quality so a choppy
    range and a clean stair stop reading identically."""

    @staticmethod
    def _frame(highs: list[float], lows: list[float], closes: list[float]) -> pd.DataFrame:
        return pd.DataFrame({"high": highs, "low": lows, "close": closes}, dtype=float)

    def test_hand_computed_period3_example(self) -> None:
        # 7 bars, period 3 (>= 2*3+1). DM/TR on bars 1..6 (+DM needs a
        # rising high; -DM needs a FALLING low, not a rising one):
        #   +DM [0.5, 0.5, 0.8, 0, 0, 0.3], -DM [0, 0, 0, 0.5, 0.6, 0],
        #   TR  [1.1, 1.2, 1.4, 1.6, 1.3, 1.3]
        # seeds (mean of first 3): s+=0.6, s-=0, sTR=37/30
        # i=3: s+=2/5, s-=1/6, sTR=61/45 -> DI+ 1800/61, DI- 750/61
        #      -> DX = 1050/2550*100 = 41.1765
        # i=4: s+=4/15, s-=14/45, sTR=361/270 -> DI+ 7200/361, DI- 8400/361
        #      -> DX = 1200/15600*100 = 7.6923
        # i=5: s+=5/18, s-=28/135, sTR=1073/810 -> DI+ 22500/1073, DI- 16800/1073
        #      -> DX = 5700/39300*100 = 14.5038
        # ADX = mean(41.1765, 7.6923, 14.5038) = 21.1242
        from app.analysis.technical.daily import _adx as impl

        adx = impl(
            self._frame(
                highs=[10.0, 10.5, 11.0, 11.8, 11.2, 10.6, 10.9],
                lows=[9.0, 9.4, 9.8, 10.4, 9.9, 9.3, 9.6],
                closes=[9.5, 10.2, 10.8, 11.5, 10.5, 9.8, 10.1],
            ),
            period=3,
        )
        assert adx == pytest.approx(21.1242, abs=1e-3)

    def test_matches_ewm_reference_implementation(self) -> None:
        # Independent vectorized formulation: Wilder smoothing = EMA with
        # alpha=1/period seeded by the SMA of the first window, applied
        # twice (DM->DI, DX->ADX) must agree with the loop implementation.
        import numpy as np

        closes = [100 + 2 * math.sin(i / 5) + (i % 7) * 0.3 - 0.9 for i in range(120)]
        highs = [c + 0.5 + (i % 5) * 0.1 for i, c in enumerate(closes)]
        lows = [c - 0.4 - (i % 3) * 0.15 for i, c in enumerate(closes)]
        period = 14

        close_s = pd.Series(closes)
        up = pd.Series(highs).diff()
        down = -(pd.Series(lows).diff())
        plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0)).iloc[1:]
        minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0)).iloc[1:]
        tr = (
            pd.concat(
                [
                    pd.Series(highs) - pd.Series(lows),
                    (pd.Series(highs) - close_s.shift()).abs(),
                    (pd.Series(lows) - close_s.shift()).abs(),
                ],
                axis=1,
            )
            .max(axis=1)
            .iloc[1:]
        )

        def wilder(s: pd.Series) -> pd.Series:
            seed = s.iloc[:period].mean()
            padded = pd.concat([pd.Series([seed]), s.iloc[period:]], ignore_index=True)
            return padded.ewm(alpha=1 / period, adjust=False).mean()

        di_plus = 100 * wilder(plus_dm) / wilder(tr)
        di_minus = 100 * wilder(minus_dm) / wilder(tr)
        denom = di_plus + di_minus
        dx = (100 * (di_plus - di_minus).abs() / denom.where(denom > 0)).iloc[1:].dropna()
        dx = dx.reset_index(drop=True)
        ref = float(wilder(dx.reset_index(drop=True)).iloc[-1])

        from app.analysis.technical.daily import _adx as impl

        got = impl(pd.DataFrame({"high": highs, "low": lows, "close": closes}), period=period)
        # The engine rounds to 4 decimals; the reference agrees to that digit.
        assert got == pytest.approx(ref, abs=1e-4)

    def test_clean_uptrend_reads_strong_choppy_range_reads_weak(self) -> None:
        # Stair up (steady +0.8% closes, 1% ranges) -> one-sided direction.
        result = analyze_daily(_daily(days=200), symbol="AAPL", source="test")
        assert result["indicators"]["adx"] >= 25
        assert result["signals"]["trend_strength"] in ("strong", "very_strong")

        # Symmetric alternation: +DM and -DM balance, DX -> ~0, ADX < 20.
        days = 200
        closes = [100.0 + (0.8 if i % 2 == 0 else -0.8) for i in range(days)]
        choppy = {
            "dates": [d.isoformat() for d in pd.bdate_range("2023-08-01", periods=days)],
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [1_000_000.0] * days,
        }
        result = analyze_daily(choppy, symbol="XYZ", source="test")
        assert result["indicators"]["adx"] < 20
        assert result["signals"]["trend_strength"] == "weak"

    def test_warmup_gates(self) -> None:
        from app.analysis.technical.daily import _adx as impl

        closes = [10.0 + 0.1 * i for i in range(28)]
        short = self._frame([c + 0.5 for c in closes], [c - 0.5 for c in closes], closes)
        assert impl(short, period=14) is None  # 2*period bars: one DX short
        longer = self._frame(
            [c + 0.5 for c in closes] + [10.0 + 0.1 * 28],
            [c - 0.5 for c in closes] + [9.6],
            closes + [10.0 + 0.1 * 28],
        )
        assert impl(longer, period=14) is not None  # 2*period+1 bars exactly

    def test_flat_tape_returns_none(self) -> None:
        from app.analysis.technical.daily import _adx as impl

        n = 60
        flat = self._frame([10.0] * n, [10.0] * n, [10.0] * n)
        assert impl(flat, period=14) is None  # zero range: no direction at all

    def test_threshold_labels(self) -> None:
        df = pd.DataFrame(
            {
                "close": [100.0] * 25,
            }
        )
        for adx, expected in [
            (19.9, "weak"),
            (20.0, "developing"),
            (24.9, "developing"),
            (25.0, "strong"),
            (49.9, "strong"),
            (50.0, "very_strong"),
        ]:
            signals = generate_signals(df, {"adx": adx, "sma_20": None, "sma_50": None})
            assert signals["trend_strength"] == expected
        # No ADX (short history) -> no opinion, key absent.
        assert "trend_strength" not in generate_signals(df, {})

    def test_evidence_includes_adx(self) -> None:
        result = analyze_daily(_daily(days=200), symbol="AAPL", source="test")
        names = [e["name"] for e in result["evidence"]]
        assert "adx_daily_14" in names
        adx_ev = next(e for e in result["evidence"] if e["name"] == "adx_daily_14")
        assert adx_ev["value"] == result["indicators"]["adx"]
