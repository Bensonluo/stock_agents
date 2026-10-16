"""ReAct provider chain: the CN akshare fallback emits real financials.

`_akshare_cn` is what an A-share hits when the direct yfinance snapshot
yields nothing and the provider chain falls through to akshare. It used to
return `financial_data: {"metrics": {}}` — empty — so symbols landing here
lost fundamental scoring AND the valuation inputs the pipeline path emits.
These tests pin the shared-mapping contract: metrics flow through with the
canonical keys, and a dead financial feed degrades to the old empty
behavior while the market data survives.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pandas as pd
import pytest

from app.config import get_settings
from app.tools.data.fetcher import _akshare_cn

pytestmark = pytest.mark.asyncio

_HIST_COLUMNS = ("日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额")
_HIST_ROWS = [
    ("2026-09-22", 10.0, 10.2, 10.3, 9.9, 900_000, 9.2e8),
    ("2026-09-23", 10.2, 10.4, 10.5, 10.1, 950_000, 9.9e8),
    ("2026-09-24", 10.4, 10.5, 10.6, 10.3, 880_000, 9.2e8),
]

# The LIVE Sina indicator table (akshare 1.18.96) — unit-suffixed columns,
# same fixture shape as the pipeline agent's tests, decoy included.
_FINANCIAL_COLUMNS = (
    "摊薄每股收益(元)",
    "加权净资产收益率(%)",  # decoy: must never satisfy a 净资产收益率 lookup
    "净资产收益率(%)",
    "总资产净利润率(%)",
    "销售毛利率(%)",
    "销售净利率(%)",
    "资产负债率(%)",
    "流动比率",
    "速动比率",
    "净利润增长率(%)",
    "主营业务收入增长率(%)",
)
_FINANCIAL_VALUES = (3.2, 25.0, 31.0, 19.0, 91.0, 49.0, 21.0, 4.2, 3.9, 12.0, 9.0)


class _FakeAk:
    """Stands in for the akshare module; `ak` is a plain parameter here."""

    def __init__(
        self,
        *,
        financial_error: Exception | None = None,
        financial_frame: pd.DataFrame | None = None,
    ):
        self._financial_error = financial_error
        self._financial_frame = financial_frame

    def stock_zh_a_hist(self, symbol: str, **kwargs: Any) -> pd.DataFrame:
        assert kwargs.get("period") == "daily"
        assert kwargs.get("adjust") == "qfq"
        return pd.DataFrame([dict(zip(_HIST_COLUMNS, row)) for row in _HIST_ROWS])

    def stock_financial_analysis_indicator(self, symbol: str) -> pd.DataFrame:
        if self._financial_error is not None:
            raise self._financial_error
        if self._financial_frame is not None:
            return self._financial_frame
        return pd.DataFrame([dict(zip(_FINANCIAL_COLUMNS, _FINANCIAL_VALUES))])


async def test_provider_emits_canonical_cn_metrics() -> None:
    """Metrics must flow through with the pipeline path's keys and units."""
    result = await _akshare_cn("600519", _FakeAk())

    metrics = result["financial_data"]["metrics"]
    assert metrics["roe"] == 0.31  # ratio, not the raw 31.0 percent
    assert metrics["profit_margin"] == 0.49  # canonical key, not net_margin
    assert metrics["trailing_eps"] == 3.2  # valuation input, not ratio-scaled
    assert metrics["earnings_growth"] == 0.12
    assert metrics["revenue_growth"] == 0.09
    # The decoy 加权净资产收益率 must not have leaked into ROE.
    assert metrics["roe"] != 0.25

    # Market data unchanged by the enrichment: last-bar close drives price.
    market = result["market_data"]
    assert market["current_price"] == 10.5
    assert market["previous_close"] == 10.4
    assert market["historical_data"]["amount"] == [9.2e8, 9.9e8, 9.2e8]


async def test_financial_feed_failure_degrades_to_empty_metrics() -> None:
    """A dead financial feed keeps the market data (the old behavior)."""
    result = await _akshare_cn("600519", _FakeAk(financial_error=RuntimeError("sina down")))

    assert result["financial_data"] == {"metrics": {}}
    assert result["market_data"]["current_price"] == 10.5
    assert result["market_data"]["historical_data"]["dates"] == [
        "2026-09-22",
        "2026-09-23",
        "2026-09-24",
    ]


# --------------------------------------------------------------------------
# Trend depth: the FULL dated indicator table rides along as history
# --------------------------------------------------------------------------

# 日期 + the live columns; rows oldest-first the way akshare sorts them.
# The 2025 row carries a NaN growth cell — AkShare marks missing periods
# that way and the history block must not leak it into JSON.
_HISTORY_COLUMNS = ("日期",) + _FINANCIAL_COLUMNS
_HISTORY_ROWS = [
    (date(2025, 12, 31), 3.0, 25.0, 28.0, 17.0, 90.0, 45.0, 20.0, 4.0, 3.7, float("nan"), 7.0),
    (date(2026, 6, 30), 3.1, 24.0, 30.0, 18.0, 91.0, 48.0, 20.5, 4.1, 3.8, 10.0, 8.0),
    (date(2026, 9, 30), 3.2, 25.0, 31.0, 19.0, 91.0, 49.0, 21.0, 4.2, 3.9, 12.0, 9.0),
]


def _dated_indicator_frame() -> pd.DataFrame:
    return pd.DataFrame([dict(zip(_HISTORY_COLUMNS, row)) for row in _HISTORY_ROWS])


async def test_full_indicator_history_rides_the_cn_fetch() -> None:
    """Trend depth on: every dated row maps with the same canonical keys and
    units as the metrics block — per-period trend points, not just latest."""
    result = await _akshare_cn("600519", _FakeAk(financial_frame=_dated_indicator_frame()))

    history = result["financial_data"]["indicators_history"]
    assert [row["date"] for row in history] == ["2025-12-31", "2026-06-30", "2026-09-30"]
    # Per-period mapping: each row's ROE is that row's cell as a ratio,
    # and the NaN growth cell degrades to None instead of poisoning JSON.
    assert [row["metrics"]["roe"] for row in history] == [0.28, 0.30, 0.31]
    assert history[0]["metrics"]["earnings_growth"] is None
    assert history[1]["metrics"]["earnings_growth"] == 0.10
    json.loads(json.dumps(history))  # JSON boundary holds


async def test_history_latest_row_matches_the_metrics_block() -> None:
    """The metrics block IS the last history row — one shared mapper, so the
    two can never drift apart."""
    result = await _akshare_cn("600519", _FakeAk(financial_frame=_dated_indicator_frame()))

    history = result["financial_data"]["indicators_history"]
    assert history[-1]["metrics"] == result["financial_data"]["metrics"]


async def test_trend_depth_off_keeps_history_dark() -> None:
    """Toggle off = exactly the pre-trend behavior: latest-row metrics only."""
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(get_settings(), "trend_depth_enabled", False)
    try:
        result = await _akshare_cn("600519", _FakeAk(financial_frame=_dated_indicator_frame()))
    finally:
        monkeypatch.undo()

    assert "indicators_history" not in result["financial_data"]
    assert result["financial_data"]["metrics"]["roe"] == 0.31


async def test_undateable_rows_are_skipped_from_history() -> None:
    """A frame without the 日期 column (degraded/partial provider shape, the
    pre-trend fixture) can still yield latest-row metrics — but a trend point
    without a date is unplaceable, so no history block is emitted."""
    result = await _akshare_cn("600519", _FakeAk())

    assert "indicators_history" not in result["financial_data"]
    assert result["financial_data"]["metrics"]["roe"] == 0.31
