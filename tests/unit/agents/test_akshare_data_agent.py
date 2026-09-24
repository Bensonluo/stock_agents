"""AkShareDataAgent fetch economics and column mapping.

The spot table (stock_zh_a_spot_em) is the ENTIRE A-share market (~5000
rows) in one response; these tests pin the one-round-trip-per-run contract
and the 涨跌额/涨跌幅 column mapping, with graceful degradation when the
table fetch fails.
"""

from __future__ import annotations

import sys
import threading
import time
import types
from typing import Any

import pandas as pd
import pytest

from app.agents.data_agent import (
    AkShareDataAgent,
    _debt_to_equity_from_asset_ratio,
    _pct_to_ratio,
    _sync_fetch_akshare_financials,
)
from app.analysis.fundamental.scoring import analyze_fundamental_scoring

pytestmark = pytest.mark.asyncio

_SPOT_COLUMNS = (
    "代码",
    "最新价",
    "涨跌额",
    "涨跌幅",
    "成交量",
    "成交额",
    "振幅",
    "最高",
    "最低",
    "今开",
    "昨收",
)

_SPOT_ROWS = [
    ("600519", 1650.0, 19.5, 1.2, 25_000, 4.1e9, 2.1, 1660.0, 1635.0, 1640.0, 1630.5),
    ("000001", 10.5, 0.2, 1.9, 900_000, 9.4e8, 1.4, 10.6, 10.3, 10.4, 10.3),
    ("300750", 210.0, -4.0, -1.9, 60_000, 1.3e9, 2.8, 216.0, 209.0, 214.0, 214.0),
]

_FINANCIAL_COLUMNS = (
    "净资产收益率",
    "总资产净利率",
    "销售毛利率",
    "销售净利率",
    "资产负债率",
    "流动比率",
    "速动比率",
)


class _FakeAk:
    """Stands in for the akshare module; counts network round-trips."""

    def __init__(
        self,
        *,
        spot_error: Exception | None = None,
        hist_error: Exception | None = None,
        hist_empty: bool = False,
    ):
        self.spot_calls = 0
        self.hist_calls: list[str] = []
        self.financial_calls: list[str] = []
        self._spot_error = spot_error
        self._hist_error = hist_error
        self._hist_empty = hist_empty

    def stock_zh_a_spot_em(self) -> pd.DataFrame:
        self.spot_calls += 1
        if self._spot_error is not None:
            raise self._spot_error
        return pd.DataFrame([dict(zip(_SPOT_COLUMNS, row)) for row in _SPOT_ROWS])

    def stock_zh_a_hist(self, symbol: str, **kwargs) -> pd.DataFrame:
        self.hist_calls.append(symbol)
        if self._hist_error is not None:
            raise self._hist_error
        if self._hist_empty:
            return pd.DataFrame()
        assert kwargs.get("period") == "daily"
        assert kwargs.get("adjust") == "qfq"
        rows = [
            ("2026-09-22", 1600.0, 1620.0, 1625.0, 1595.0, 24_000),
            ("2026-09-23", 1620.0, 1640.0, 1648.0, 1615.0, 26_500),
            ("2026-09-24", 1640.0, 1650.0, 1660.0, 1635.0, 25_000),
        ]
        return pd.DataFrame(
            [dict(zip(("日期", "开盘", "收盘", "最高", "最低", "成交量"), row)) for row in rows]
        )

    def stock_financial_analysis_indicator(self, symbol: str) -> pd.DataFrame:
        self.financial_calls.append(symbol)
        values = (31.0, 19.0, 91.0, 49.0, 21.0, 4.2, 3.9)
        return pd.DataFrame([dict(zip(_FINANCIAL_COLUMNS, values))])


def _install_fake_ak(monkeypatch: pytest.MonkeyPatch, fake: _FakeAk) -> None:
    """Route the agent's `import akshare as ak` to the fake."""
    module = types.ModuleType("akshare")
    module.stock_zh_a_spot_em = fake.stock_zh_a_spot_em  # type: ignore[attr-defined]
    module.stock_zh_a_hist = fake.stock_zh_a_hist  # type: ignore[attr-defined]
    module.stock_financial_analysis_indicator = (  # type: ignore[attr-defined]
        fake.stock_financial_analysis_indicator
    )
    monkeypatch.setitem(sys.modules, "akshare", module)


async def _run(monkeypatch: pytest.MonkeyPatch, symbols: list[str], **fake_kwargs: Any):
    fake = _FakeAk(**fake_kwargs)
    _install_fake_ak(monkeypatch, fake)
    agent = AkShareDataAgent("akshare_data")
    agent.llm = None
    result = await agent.execute({"symbols": symbols})
    return fake, result


class TestSpotTableFetchEconomics:
    async def test_spot_table_fetched_once_for_multiple_symbols(self, monkeypatch):
        """N CN symbols must mean ONE spot-table round-trip, not N."""
        fake, result = await _run(monkeypatch, ["600519", "000001", "300750"])

        assert fake.spot_calls == 1
        assert set(result["market_data"]) == {"600519", "000001", "300750"}
        assert set(result["financial_data"]) == {"600519", "000001", "300750"}

    async def test_non_cn_symbols_are_skipped(self, monkeypatch):
        fake, result = await _run(monkeypatch, ["AAPL", "600519"])

        assert "AAPL" not in result["market_data"]
        assert "600519" in result["market_data"]
        assert fake.financial_calls == ["600519"]

    async def test_symbol_missing_from_table_has_no_market_row(self, monkeypatch):
        _, result = await _run(monkeypatch, ["600519", "999999"])

        assert "999999" not in result["market_data"]
        assert "600519" in result["market_data"]
        assert "999999" in result["financial_data"]  # financials are a separate feed

    async def test_spot_fetch_failure_degrades_but_financials_survive(self, monkeypatch):
        """Spot table down != agent down: financial feed still collected."""
        fake, result = await _run(
            monkeypatch, ["600519", "000001"], spot_error=RuntimeError("eastmoney down")
        )

        assert fake.spot_calls == 1
        assert result["market_data"] == {}
        assert set(result["financial_data"]) == {"600519", "000001"}


class TestColumnMapping:
    async def test_change_is_absolute_amount_not_percent(self, monkeypatch):
        """`change` must come from 涨跌额 (absolute), not re-read 涨跌幅."""
        _, result = await _run(monkeypatch, ["600519"])
        mkt = result["market_data"]["600519"]

        assert mkt["change"] == 19.5
        assert mkt["change_percent"] == 1.2

    async def test_market_row_shape(self, monkeypatch):
        _, result = await _run(monkeypatch, ["300750"])
        mkt = result["market_data"]["300750"]

        assert mkt["symbol"] == "300750"
        assert mkt["current_price"] == 210.0
        assert mkt["previous_close"] == 214.0
        assert mkt["open"] == 214.0
        assert mkt["high"] == 216.0
        assert mkt["low"] == 209.0
        assert mkt["timestamp"]  # stamped for downstream staleness checks


class TestHistoryBars:
    async def test_daily_bars_attached_in_yfinance_shape(self, monkeypatch):
        """CN symbols get historical_data so technical analysis can run."""
        fake, result = await _run(monkeypatch, ["600519"])
        hist = result["market_data"]["600519"]["historical_data"]

        assert fake.hist_calls == ["600519"]
        assert set(hist) == {"dates", "open", "high", "low", "close", "volume"}
        assert hist["dates"] == ["2026-09-22", "2026-09-23", "2026-09-24"]
        assert hist["open"] == [1600.0, 1620.0, 1640.0]  # from 开盘
        assert hist["close"] == [1620.0, 1640.0, 1650.0]  # from 收盘
        assert hist["volume"] == [24_000, 26_500, 25_000]
        # as_of tracks the last bar, not the fetch time
        assert result["market_data"]["600519"]["as_of"] == "2026-09-24"

    async def test_history_failure_degrades_to_spot_only(self, monkeypatch):
        """Bars down: symbol keeps its spot row (iter-16 degradation path)."""
        _, result = await _run(monkeypatch, ["600519"], hist_error=RuntimeError("hist feed down"))
        mkt = result["market_data"]["600519"]

        assert mkt["symbol"] == "600519"
        assert "historical_data" not in mkt
        assert "as_of" not in mkt

    async def test_empty_history_degrades_to_spot_only(self, monkeypatch):
        _, result = await _run(monkeypatch, ["600519"], hist_empty=True)
        assert "historical_data" not in result["market_data"]["600519"]


class _SlowFakeAk(_FakeAk):
    """Hist feed with real latency and thread-safe in-flight tracking.

    The in-flight counter is the regression signal: if per-symbol fetching
    ever reverts to a serial loop, no two hist calls overlap and
    max_in_flight stays at 1.
    """

    def __init__(self, symbols: list[str]):
        super().__init__()
        self._symbols = list(symbols)
        self._lock = threading.Lock()
        self._in_flight = 0
        self.max_in_flight = 0

    def stock_zh_a_spot_em(self) -> pd.DataFrame:
        self.spot_calls += 1
        row = (100.0, 1.0, 1.0, 1_000, 1e8, 1.0, 101.0, 99.0, 100.0, 99.0)
        return pd.DataFrame([dict(zip(_SPOT_COLUMNS, (sym, *row))) for sym in self._symbols])

    def stock_zh_a_hist(self, symbol: str, **kwargs) -> pd.DataFrame:
        with self._lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            time.sleep(0.02)  # long enough that concurrent calls genuinely overlap
            return super().stock_zh_a_hist(symbol, **kwargs)
        finally:
            with self._lock:
                self._in_flight -= 1


class TestConcurrentPerSymbolFetch:
    async def test_history_fetches_overlap_but_respect_the_semaphore(self, monkeypatch):
        """Per-symbol work must fan out concurrently, capped at 5 in flight."""
        symbols = ["600000", "600001", "600002", "600003", "600004", "600005"]
        fake = _SlowFakeAk(symbols)
        _install_fake_ak(monkeypatch, fake)
        agent = AkShareDataAgent("akshare_data")
        agent.llm = None

        result = await agent.execute({"symbols": symbols})

        assert fake.spot_calls == 1
        assert 2 <= fake.max_in_flight <= 5  # overlapped, but bounded
        assert set(result["market_data"]) == set(symbols)
        assert set(result["financial_data"]) == set(symbols)

    async def test_output_order_follows_request_order(self, monkeypatch):
        """gather preserves input order, so market_data keys stay deterministic."""
        symbols = ["300750", "600519", "000001"]
        fake = _SlowFakeAk(symbols)
        _install_fake_ak(monkeypatch, fake)
        agent = AkShareDataAgent("akshare_data")
        agent.llm = None

        result = await agent.execute({"symbols": symbols})

        assert list(result["market_data"]) == symbols
        assert list(result["financial_data"]) == symbols


async def test_financial_metrics_use_canonical_names_and_ratio_units() -> None:
    """CN financials must speak the same keys/units as the yfinance path."""
    metrics = _sync_fetch_akshare_financials("600519", _FakeAk())["metrics"]

    assert metrics["roe"] == 0.31  # 31% as a ratio, not the raw percent
    assert metrics["roa"] == 0.19
    assert metrics["gross_margin"] == 0.91
    assert metrics["profit_margin"] == 0.49  # canonical name, not net_margin
    assert metrics["debt_to_asset"] == 0.21
    assert metrics["debt_to_equity"] == pytest.approx(0.21 / 0.79)
    assert metrics["current_ratio"] == 4.2
    assert "net_margin" not in metrics


async def test_debt_to_equity_conversion_edges() -> None:
    assert _debt_to_equity_from_asset_ratio(50.0) == 1.0
    assert _debt_to_equity_from_asset_ratio(100.0) is None  # wiped-out equity
    assert _debt_to_equity_from_asset_ratio(0.0) is None
    assert _debt_to_equity_from_asset_ratio(None) is None
    assert _pct_to_ratio(float("nan")) is None  # AkShare missing periods
    assert _pct_to_ratio("--") is None


async def test_canonical_cn_metrics_actually_score() -> None:
    """Mapped keys must land in scoring buckets — renamed keys scored zero."""
    metrics = _sync_fetch_akshare_financials("600519", _FakeAk())["metrics"]

    result = analyze_fundamental_scoring({"600519": {"metrics": metrics}})["600519"]

    # roe 0.31 -> 40, roa 0.19 -> 20, profit_margin 0.49 -> 20: raw 80 of
    # 80 achievable (no operating_margin) -> normalized 100 since it. 41.
    assert result["profitability"]["score"] == 100
    # d/e 0.266 -> 40, current 4.2 -> 30, quick 3.9 -> 30: full 100 of 100.
    assert result["financial_health"]["score"] == 100


async def test_ratio_units_land_in_the_right_bucket() -> None:
    """8% ROE is a +10 bucket as 0.08; the raw percent 8.0 maxed every tier."""
    scored = analyze_fundamental_scoring({"S": {"metrics": {"roe": _pct_to_ratio(8.0)}}})

    profitability = scored["S"]["profitability"]
    assert profitability["score"] == 25.0  # 10 raw of 40 achievable
    assert profitability["metrics_count"] == 1
    assert profitability["details"] == {"roe": 0.08}
