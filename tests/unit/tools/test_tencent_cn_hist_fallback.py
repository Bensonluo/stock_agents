"""Tencent fallback for A-share daily bars when East Money is blocked.

Production (Tencent Cloud host) verified 2026-09-27: push2his.eastmoney.com
is domain-level blocked — akshare's ``stock_zh_a_hist`` AND bare curl both
get TCP-dropped — while Tencent's kline endpoints answer from the same box.
``stock_zh_a_hist_tx`` is the fallback source, with contract traps pinned
here: its ``symbol`` needs the sh/sz market prefix, and its volume column is
股 (shares) where East Money's 成交量 is 手 (100-share lots) — amount is
yuan in both. Every scenario runs offline against fake akshare modules; the
local sandbox proxy poisons real-network tests.
"""

from __future__ import annotations

import http.client
import re
import sys
import types
from datetime import date
from typing import Any

import pandas as pd
import pytest

import app.tools.data.fetcher as fetcher_mod
import app.tools.data.fetcher_cn as fetcher_cn_mod
from app.config import get_settings
from app.tools.data.fetcher import _cn_tencent_symbol, fetch_historical

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


class _RecorderAk:
    """Stands in for the akshare module; records every call's arguments."""

    def __init__(
        self,
        *,
        em_frame: pd.DataFrame | None = None,
        em_error: Exception | None = None,
        tx_frame: pd.DataFrame | None = None,
        tx_error: Exception | None = None,
    ) -> None:
        self.em_calls: list[dict[str, Any]] = []
        self.tx_calls: list[dict[str, Any]] = []
        self._em_frame = em_frame
        self._em_error = em_error
        self._tx_frame = tx_frame
        self._tx_error = tx_error

    def stock_zh_a_hist(self, **kwargs: Any) -> pd.DataFrame:
        self.em_calls.append(kwargs)
        if self._em_error is not None:
            raise self._em_error
        return self._em_frame

    def stock_zh_a_hist_tx(self, **kwargs: Any) -> pd.DataFrame:
        self.tx_calls.append(kwargs)
        if self._tx_error is not None:
            raise self._tx_error
        return self._tx_frame


class _DeadYf:
    @staticmethod
    def Ticker(symbol: str):  # noqa: N802 - yfinance API shape
        raise RuntimeError("Too Many Requests")


@pytest.fixture(autouse=True)
def _clear_caches():
    fetcher_mod._cache.clear()
    yield
    fetcher_mod._cache.clear()


@pytest.fixture(autouse=True)
def _offline_state(monkeypatch: pytest.MonkeyPatch):
    """Finnhub/AV stay out of the chain; the fake akshare is the only source."""
    settings = get_settings()
    monkeypatch.setattr(settings, "finnhub_api_key", None)
    monkeypatch.setattr(settings, "alpha_vantage_key", None)


def _install_ak(monkeypatch: pytest.MonkeyPatch, fake: _RecorderAk) -> None:
    module = types.ModuleType("akshare")
    module.stock_zh_a_hist = fake.stock_zh_a_hist  # type: ignore[attr-defined]
    module.stock_zh_a_hist_tx = fake.stock_zh_a_hist_tx  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "akshare", module)
    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=_DeadYf.Ticker))


class TestTencentSymbolPrefix:
    def test_sh_sz_split_follows_the_yahoo_convention(self) -> None:
        """6 -> sh, 0/3 -> sz — the same split as `_convert_to_yahoo_symbol`
        (including its Shanghai default for anything else)."""
        assert _cn_tencent_symbol("600519") == "sh600519"
        assert _cn_tencent_symbol("688001") == "sh688001"
        assert _cn_tencent_symbol("000001") == "sz000001"
        assert _cn_tencent_symbol("300750") == "sz300750"
        assert _cn_tencent_symbol("400001") == "sh400001"


class TestHelperMapping:
    def test_tx_frame_maps_to_the_em_column_contract(self) -> None:
        """date/open/close/high/low/volume/amount -> 日期/开盘/收盘/最高/
        最低/成交量/成交额 with volume 股 -> 手 and amount untouched."""
        fake = _RecorderAk(tx_frame=_tx_frame())
        df = fetcher_mod._sync_fetch_tencent_cn_hist("600519", fake, 365)

        assert df is not None
        assert df["成交量"].tolist() == [24_000, 26_500, 25_000]
        assert df["成交额"].tolist() == list(_AMOUNTS_YUAN)
        assert df["开盘"].tolist() == [1600.0, 1620.0, 1640.0]
        # datetime.date flows through, exactly like EM's 日期 column.
        assert [str(d) for d in df["日期"].tolist()] == list(_DATES)

    def test_tx_call_carries_prefix_qfq_and_window(self) -> None:
        fake = _RecorderAk(tx_frame=_tx_frame())
        fetcher_mod._sync_fetch_tencent_cn_hist("600519", fake, 365)

        call = fake.tx_calls[0]
        assert call["symbol"] == "sh600519"
        assert call["adjust"] == "qfq"
        assert re.match(r"^\d{8}$", call["start_date"])
        assert re.match(r"^\d{8}$", call["end_date"])

    def test_tx_failure_returns_none(self) -> None:
        fake = _RecorderAk(tx_error=ConnectionError("TCP dropped"))
        assert fetcher_mod._sync_fetch_tencent_cn_hist("600519", fake, 365) is None

    def test_tx_empty_returns_none(self) -> None:
        fake = _RecorderAk(tx_frame=pd.DataFrame())
        assert fetcher_mod._sync_fetch_tencent_cn_hist("600519", fake, 365) is None


class TestFetchHistoricalFallback:
    @pytest.mark.asyncio
    async def test_em_disconnect_falls_back_to_tencent(self, monkeypatch) -> None:
        """The production failure shape (TCP drop mid-response) must land on
        Tencent bars in the exact EM result shape, volume converted 股 -> 手."""
        fake = _RecorderAk(
            em_error=http.client.RemoteDisconnected(
                "Remote end closed connection without response"
            ),
            tx_frame=_tx_frame(),
        )
        _install_ak(monkeypatch, fake)

        result = await fetch_historical("600519", "3y")

        assert len(fake.em_calls) == 1
        assert len(fake.tx_calls) == 1
        assert result["symbol"] == "600519"
        assert result["period"] == "3y"
        assert result["dates"] == list(_DATES)
        assert result["open"] == [1600.0, 1620.0, 1640.0]
        assert result["high"] == [1625.0, 1645.0, 1665.0]
        assert result["low"] == [1595.0, 1615.0, 1635.0]
        assert result["close"] == [1620.0, 1640.0, 1660.0]
        # 2_400_000 股 / 100 == 24_000 手 — the unit EM has always emitted.
        assert result["volume"] == [24_000, 26_500, 25_000]

    @pytest.mark.asyncio
    async def test_em_connection_error_falls_back_to_tencent(self, monkeypatch) -> None:
        """The other production shape: connect-time ConnectionError (000)."""
        fake = _RecorderAk(em_error=ConnectionError("connection dropped"), tx_frame=_tx_frame())
        _install_ak(monkeypatch, fake)

        result = await fetch_historical("600519", "3y")

        assert result["dates"] == list(_DATES)
        assert result["volume"] == [24_000, 26_500, 25_000]

    @pytest.mark.asyncio
    async def test_em_empty_frame_falls_back_to_tencent(self, monkeypatch) -> None:
        """EM answering with zero rows is also a dead feed for this symbol."""
        fake = _RecorderAk(em_frame=pd.DataFrame(), tx_frame=_tx_frame())
        _install_ak(monkeypatch, fake)

        result = await fetch_historical("600519", "3y")

        assert len(fake.tx_calls) == 1
        assert result["volume"] == [24_000, 26_500, 25_000]

    @pytest.mark.asyncio
    async def test_tencent_uses_the_same_window_as_the_em_call(self, monkeypatch) -> None:
        """Fallback window must match the EM call's parameter-for-parameter."""
        fake = _RecorderAk(em_error=ConnectionError("drop"), tx_frame=_tx_frame())
        _install_ak(monkeypatch, fake)

        await fetch_historical("000001", "1y")

        em_call, tx_call = fake.em_calls[0], fake.tx_calls[0]
        assert tx_call["symbol"] == "sz000001"
        assert tx_call["adjust"] == "qfq" == em_call["adjust"]
        assert tx_call["start_date"] == em_call["start_date"]
        assert tx_call["end_date"] == em_call["end_date"]

    @pytest.mark.asyncio
    async def test_healthy_em_never_touches_tencent(self, monkeypatch) -> None:
        """EM healthy means the fallback must not even be attempted — the
        fallback can never shadow or alter the primary path."""
        fake = _RecorderAk(em_frame=_em_frame(), tx_error=RuntimeError("must not run"))
        _install_ak(monkeypatch, fake)

        result = await fetch_historical("600519", "3y")

        assert fake.tx_calls == []
        assert result["volume"] == [24_000, 26_500, 25_000]
        assert set(result) == {
            "symbol",
            "period",
            "dates",
            "open",
            "high",
            "low",
            "close",
            "volume",
        }

    @pytest.mark.asyncio
    async def test_both_sources_fail_degrades_unchanged(self, monkeypatch) -> None:
        """Tencent failing too must land on the pre-existing total-failure
        return — an extra attempted hop, not a new failure mode."""
        fake = _RecorderAk(em_error=ConnectionError("EM drop"), tx_error=ConnectionError("tx drop"))
        _install_ak(monkeypatch, fake)

        def _dead_get(*args: Any, **kwargs: Any):
            raise ConnectionError("no network")

        monkeypatch.setattr(fetcher_mod.requests, "get", _dead_get)

        result = await fetch_historical("600519", "3y")

        assert result == {"error": "All providers failed for 600519", "symbol": "600519"}

    @pytest.mark.asyncio
    async def test_volume_units_are_identical_across_sources(self, monkeypatch) -> None:
        """The same market days expressed in each source's native unit must
        emit identical volume series (手) — a 100x unit slip here would
        distort every volume-based indicator by two orders of magnitude."""
        em_fake = _RecorderAk(em_frame=_em_frame())
        _install_ak(monkeypatch, em_fake)
        via_em = await fetch_historical("600519", "3y")
        fetcher_mod._cache.clear()

        fb_fake = _RecorderAk(em_error=ConnectionError("drop"), tx_frame=_tx_frame())
        _install_ak(monkeypatch, fb_fake)
        via_tx = await fetch_historical("600519", "3y")

        assert via_tx["volume"] == via_em["volume"]
        assert set(via_tx) == set(via_em)  # no stray keys from the tx path


_FAKE_FINANCIALS = {
    "symbol": "600519",
    "metrics": {"roe": 0.31, "trailing_eps": 64.0},
    "timestamp": "2026-09-28T00:00:00",
}


async def _run_cn_snapshot(
    monkeypatch: pytest.MonkeyPatch, fake: _RecorderAk
) -> dict[str, Any] | None:
    """Run the ReAct/provider-chain CN snapshot (`_akshare_cn`) offline.

    ``_akshare_cn`` takes the akshare module as an argument, so the recorder
    IS the module here — no sys.modules install needed. The financials seam
    (datacenter-web/Sina, still alive in production while EM is blocked) is
    faked to pin that it survives the history outage.
    """
    monkeypatch.setattr(
        fetcher_cn_mod, "_sync_fetch_akshare_financials", lambda symbol, ak: _FAKE_FINANCIALS
    )
    return await fetcher_mod._akshare_cn("600519", fake)


class TestAkshareCNSnapshotFallback:
    """Third history entry point: the ReAct/provider-chain CN snapshot.

    Before the fix, an East Money outage inside ``_akshare_cn._get_hist``
    blew through to ``_akshare_fetch``'s blanket except — the whole snapshot
    died, including the still-alive financials chain that only runs after
    the history gate. The empty-frame variant killed it the same way. Here
    the snapshot gets the same Tencent fallback seam as ``fetch_historical``
    and the pipeline's AkShare agent.
    """

    @pytest.mark.asyncio
    async def test_em_disconnect_falls_back_and_keeps_financials(self, monkeypatch) -> None:
        """The production failure shape (TCP drop mid-response) must land on
        Tencent-derived prices with the financial chain still assembled."""
        fake = _RecorderAk(
            em_error=http.client.RemoteDisconnected(
                "Remote end closed connection without response"
            ),
            tx_frame=_tx_frame(),
        )

        result = await _run_cn_snapshot(monkeypatch, fake)

        assert len(fake.em_calls) == 1
        assert len(fake.tx_calls) == 1
        mkt = result["market_data"]
        # current/prev derive from the tx closes, not a dead EM feed.
        assert mkt["current_price"] == 1660.0
        assert mkt["previous_close"] == 1640.0
        assert mkt["change"] == 20.0
        # tx 股 -> 手: the unit the EM path has always emitted.
        assert mkt["volume"] == 25_000
        hist = mkt["historical_data"]
        assert hist["close"] == [1620.0, 1640.0, 1660.0]
        assert hist["volume"] == [24_000, 26_500, 25_000]
        assert hist["amount"] == list(_AMOUNTS_YUAN)
        # The datacenter-web financial chain must survive the EM outage —
        # this is what the pre-fix blow-up silently killed.
        assert result["financial_data"] == _FAKE_FINANCIALS

    @pytest.mark.asyncio
    async def test_em_empty_frame_falls_back_to_tencent(self, monkeypatch) -> None:
        """EM answering with zero rows is also a dead feed for this symbol."""
        fake = _RecorderAk(em_frame=pd.DataFrame(), tx_frame=_tx_frame())

        result = await _run_cn_snapshot(monkeypatch, fake)

        assert len(fake.tx_calls) == 1
        assert result["market_data"]["current_price"] == 1660.0
        assert result["market_data"]["historical_data"]["amount"] == list(_AMOUNTS_YUAN)

    @pytest.mark.asyncio
    async def test_healthy_em_never_touches_tencent(self, monkeypatch) -> None:
        """EM healthy means the fallback must not even be attempted, and the
        snapshot stays bit-for-bit what the EM path has always emitted."""
        fake = _RecorderAk(em_frame=_em_frame(), tx_error=RuntimeError("must not run"))

        result = await _run_cn_snapshot(monkeypatch, fake)

        assert fake.tx_calls == []
        assert result["market_data"] == {
            "symbol": "600519",
            "current_price": 1660.0,
            "previous_close": 1640.0,
            "change": 20.0,
            "change_percent": (1660.0 - 1640.0) / 1640.0 * 100,
            "volume": 25_000,
            "historical_data": {
                "dates": list(_DATES),
                "open": [1600.0, 1620.0, 1640.0],
                "high": [1625.0, 1645.0, 1665.0],
                "low": [1595.0, 1615.0, 1635.0],
                "close": [1620.0, 1640.0, 1660.0],
                "volume": [24_000, 26_500, 25_000],
                "amount": list(_AMOUNTS_YUAN),
            },
        }
        assert result["financial_data"] == _FAKE_FINANCIALS

    @pytest.mark.asyncio
    async def test_both_sources_fail_returns_none(self, monkeypatch) -> None:
        """Tencent failing too must land on the pre-existing total-failure
        return — an extra attempted hop, not a new failure mode."""
        fake = _RecorderAk(em_error=ConnectionError("EM drop"), tx_error=ConnectionError("tx drop"))

        assert await _run_cn_snapshot(monkeypatch, fake) is None

    @pytest.mark.asyncio
    async def test_tencent_empty_frame_returns_none(self, monkeypatch) -> None:
        """A zero-row Tencent answer is as dead as a raised one."""
        fake = _RecorderAk(em_error=ConnectionError("EM drop"), tx_frame=pd.DataFrame())

        assert await _run_cn_snapshot(monkeypatch, fake) is None
