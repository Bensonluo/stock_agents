"""AkShareDataAgent: A-share daily bars survive the East Money block.

Production (Tencent Cloud host, 2026-09-27): push2his.eastmoney.com is
domain-level blocked, so the agent's ``stock_zh_a_hist`` call dies and CN
symbols degraded to spot-only — technical analysis lost its only input.
``stock_zh_a_hist_tx`` (Tencent kline) answers from the same host; these
tests pin the agent-level fallback and its unit contract (tx volume is 股,
EM's 成交量 is 手; amount is 元 in both). Offline fake modules throughout.
"""

from __future__ import annotations

import http.client
import sys
import types
from datetime import date
from typing import Any

import pandas as pd
import pytest

from app.agents.data_agent import AkShareDataAgent

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
]

_DATES = ("2026-09-22", "2026-09-23", "2026-09-24")
# East Money contract: 成交量 in 手 (100-share lots).
_EM_VOLUME_LOTS = (24_000, 26_500, 25_000)
# Tencent contract: volume in 股 (shares) — the same market days, 100x.
_TX_VOLUME_SHARES = (2_400_000, 2_650_000, 2_500_000)
# Amount is yuan on both sides — no conversion anywhere.
_AMOUNTS_YUAN = (3.9e9, 4.1e9, 4.0e9)


def _em_frame() -> pd.DataFrame:
    """Frame exactly as akshare's stock_zh_a_hist returns it (Chinese cols)."""
    return pd.DataFrame(
        [
            {
                "日期": d,
                "开盘": 1600.0 + i * 20.0,
                "收盘": 1620.0 + i * 20.0,
                "最高": 1625.0 + i * 20.0,
                "最低": 1595.0 + i * 20.0,
                "成交量": _EM_VOLUME_LOTS[i],
                "成交额": _AMOUNTS_YUAN[i],
            }
            for i, d in enumerate(_DATES)
        ]
    )


def _tx_frame() -> pd.DataFrame:
    """Frame exactly as akshare's stock_zh_a_hist_tx returns it (verified
    against 1.18.96 source): English columns, volume in 股, amount in 元,
    date as datetime.date objects, plus the turnover extra column."""
    return pd.DataFrame(
        [
            {
                "date": date.fromisoformat(d),
                "open": 1600.0 + i * 20.0,
                "close": 1620.0 + i * 20.0,
                "high": 1625.0 + i * 20.0,
                "low": 1595.0 + i * 20.0,
                "volume": _TX_VOLUME_SHARES[i],
                "turnover": 0.5,
                "amount": _AMOUNTS_YUAN[i],
            }
            for i, d in enumerate(_DATES)
        ]
    )


class _FallbackAk:
    """Stands in for the akshare module; records EM/tx history calls."""

    def __init__(
        self,
        *,
        em_frame: pd.DataFrame | None = None,
        em_error: Exception | None = None,
        em_empty: bool = False,
        tx_frame: pd.DataFrame | None = None,
        tx_error: Exception | None = None,
    ) -> None:
        self.em_calls: list[dict[str, Any]] = []
        self.tx_calls: list[dict[str, Any]] = []
        self._em_frame = em_frame
        self._em_error = em_error
        self._em_empty = em_empty
        self._tx_frame = tx_frame
        self._tx_error = tx_error

    def stock_zh_a_spot_em(self) -> pd.DataFrame:
        return pd.DataFrame([dict(zip(_SPOT_COLUMNS, row)) for row in _SPOT_ROWS])

    def stock_zh_a_hist(self, symbol: str, **kwargs: Any) -> pd.DataFrame:
        self.em_calls.append({"symbol": symbol, **kwargs})
        if self._em_error is not None:
            raise self._em_error
        if self._em_empty:
            return pd.DataFrame()
        return self._em_frame

    def stock_zh_a_hist_tx(self, **kwargs: Any) -> pd.DataFrame:
        self.tx_calls.append(kwargs)
        if self._tx_error is not None:
            raise self._tx_error
        return self._tx_frame

    def stock_financial_analysis_indicator(self, symbol: str) -> pd.DataFrame:
        return pd.DataFrame()  # financials are not under test here


def _install_fake_ak(monkeypatch: pytest.MonkeyPatch, fake: _FallbackAk) -> None:
    module = types.ModuleType("akshare")
    module.stock_zh_a_spot_em = fake.stock_zh_a_spot_em  # type: ignore[attr-defined]
    module.stock_zh_a_hist = fake.stock_zh_a_hist  # type: ignore[attr-defined]
    module.stock_zh_a_hist_tx = fake.stock_zh_a_hist_tx  # type: ignore[attr-defined]
    module.stock_financial_analysis_indicator = (  # type: ignore[attr-defined]
        fake.stock_financial_analysis_indicator
    )
    monkeypatch.setitem(sys.modules, "akshare", module)


async def _run(monkeypatch: pytest.MonkeyPatch, fake: _FallbackAk, symbol: str = "600519"):
    _install_fake_ak(monkeypatch, fake)
    agent = AkShareDataAgent("akshare_data")
    agent.llm = None
    return await agent.execute({"symbols": [symbol]})


class TestTencentBarsFallback:
    async def test_em_disconnect_falls_back_to_tencent(self, monkeypatch) -> None:
        """The production failure shape (TCP drop) must still attach daily
        bars in the yfinance-compatible shape, volume converted 股 -> 手."""
        fake = _FallbackAk(
            em_error=http.client.RemoteDisconnected(
                "Remote end closed connection without response"
            ),
            tx_frame=_tx_frame(),
        )
        result = await _run(monkeypatch, fake)
        mkt = result["market_data"]["600519"]

        assert len(fake.tx_calls) == 1
        assert fake.tx_calls[0]["symbol"] == "sh600519"
        assert fake.tx_calls[0]["adjust"] == "qfq"
        hist = mkt["historical_data"]
        assert hist["dates"] == list(_DATES)
        assert hist["close"] == [1620.0, 1640.0, 1660.0]
        assert hist["volume"] == [24_000, 26_500, 25_000]  # 股 -> 手
        assert hist["amount"] == list(_AMOUNTS_YUAN)  # 元 both sides
        assert mkt["as_of"] == "2026-09-24"  # last bar, not fetch time

    async def test_em_empty_falls_back_to_tencent(self, monkeypatch) -> None:
        fake = _FallbackAk(em_empty=True, tx_frame=_tx_frame())
        result = await _run(monkeypatch, fake)

        assert len(fake.tx_calls) == 1
        hist = result["market_data"]["600519"]["historical_data"]
        assert hist["volume"] == [24_000, 26_500, 25_000]

    async def test_sz_symbol_gets_the_sz_prefix(self, monkeypatch) -> None:
        fake = _FallbackAk(em_error=ConnectionError("drop"), tx_frame=_tx_frame())
        await _run(monkeypatch, fake, symbol="000001")

        assert fake.tx_calls[0]["symbol"] == "sz000001"

    async def test_both_fail_degrades_to_spot_only(self, monkeypatch) -> None:
        """Tencent failing too keeps the iter-16 degradation path: spot row
        survives, bars and as_of stay absent."""
        fake = _FallbackAk(em_error=ConnectionError("EM drop"), tx_error=ConnectionError("tx drop"))
        result = await _run(monkeypatch, fake)
        mkt = result["market_data"]["600519"]

        assert mkt["symbol"] == "600519"
        assert mkt["current_price"] == 1650.0
        assert "historical_data" not in mkt
        assert "as_of" not in mkt

    async def test_healthy_em_never_touches_tencent(self, monkeypatch) -> None:
        """EM healthy means the fallback must not even be attempted — the
        fallback can never shadow the primary path."""
        fake = _FallbackAk(em_frame=_em_frame(), tx_error=RuntimeError("must not run"))
        result = await _run(monkeypatch, fake)

        assert fake.tx_calls == []
        hist = result["market_data"]["600519"]["historical_data"]
        assert hist["volume"] == [24_000, 26_500, 25_000]  # 手, unchanged

    async def test_volume_units_are_identical_across_sources(self, monkeypatch) -> None:
        """The same market days in each source's native unit must emit the
        same historical_data volume AND amount — cross-source consistency
        the liquidity/turnover layers depend on."""
        em_fake = _FallbackAk(em_frame=_em_frame())
        via_em = (await _run(monkeypatch, em_fake))["market_data"]["600519"]["historical_data"]

        tx_fake = _FallbackAk(em_error=ConnectionError("drop"), tx_frame=_tx_frame())
        via_tx = (await _run(monkeypatch, tx_fake))["market_data"]["600519"]["historical_data"]

        assert via_tx["volume"] == via_em["volume"]
        assert via_tx["amount"] == via_em["amount"]
        assert set(via_tx) == set(via_em)
