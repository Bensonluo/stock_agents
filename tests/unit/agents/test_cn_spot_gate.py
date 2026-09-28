"""AkShareDataAgent: the CN path survives a full EM spot blackout.

Production (Tencent Cloud host, 2026-09-28): push2's ``stock_zh_a_spot_em``
RemoteDisconnected. The old architecture gated history fetching behind a
truthy spot row, so iteration 95's Tencent kline fallback was unreachable
from the pipeline and the whole A-share path returned nothing. Two layers
restore it: the spot table gains a Tencent batch-quote fallback speaking
the EM column contract, and the history fetch escapes the spot gate —
both spot sources dark but kline alive now derives a minimal stock_info
from the closes (the same derivation the ReAct fetcher uses). Offline
fake akshare + faked Tencent HTTP throughout.
"""

from __future__ import annotations

import http.client
import sys
import types
from datetime import date
from typing import Any

import pandas as pd
import pytest

import app.agents.data_agent as data_agent_mod
import app.tools.data.tencent_spot as tencent_spot_mod
from app.agents.data_agent import AkShareDataAgent

pytestmark = pytest.mark.asyncio

_EM_SPOT_COLUMNS = (
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
_EM_SPOT_ROWS = [
    ("600519", 1650.0, 19.5, 1.2, 25_000, 4.1e9, 2.1, 1660.0, 1635.0, 1640.0, 1630.5),
    ("000001", 10.5, 0.2, 1.9, 900_000, 9.4e8, 1.4, 10.6, 10.3, 10.4, 10.3),
]

_DATES = ("2026-09-22", "2026-09-23", "2026-09-24")
_EM_VOLUME_LOTS = (24_000, 26_500, 25_000)
_AMOUNTS_YUAN = (3.9e9, 4.1e9, 4.0e9)


def _em_spot_frame() -> pd.DataFrame:
    """Frame exactly as akshare's stock_zh_a_spot_em returns it."""
    return pd.DataFrame([dict(zip(_EM_SPOT_COLUMNS, row)) for row in _EM_SPOT_ROWS])


def _em_hist_frame() -> pd.DataFrame:
    """East Money daily bars (Chinese columns, 成交量 in 手)."""
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


def _tx_hist_frame() -> pd.DataFrame:
    """Tencent kline bars (English columns, volume in 股)."""
    return pd.DataFrame(
        [
            {
                "date": date.fromisoformat(d),
                "open": 1600.0 + i * 20.0,
                "close": 1620.0 + i * 20.0,
                "high": 1625.0 + i * 20.0,
                "low": 1595.0 + i * 20.0,
                "volume": _EM_VOLUME_LOTS[i] * 100,
                "turnover": 0.5,
                "amount": _AMOUNTS_YUAN[i],
            }
            for i, d in enumerate(_DATES)
        ]
    )


def _tx_quote_line(
    tencent_code: str,
    name: str,
    code: str,
    price: str,
    prev_close: str,
    open_: str,
    volume_lots: str,
    high: str,
    low: str,
    amount_wan: str,
) -> bytes:
    """One GBK-encoded qt.gtimg.cn line, production anchors only."""
    fields = [""] * 40
    fields[0] = "1"
    fields[1] = name
    fields[2] = code
    fields[3] = price
    fields[4] = prev_close
    fields[5] = open_
    fields[6] = volume_lots
    fields[33] = high
    fields[34] = low
    fields[37] = amount_wan
    return (f'v_{tencent_code}="' + "~".join(fields) + '";').encode("gbk")


class _OutageAk:
    """Stands in for the akshare module; every EM seam is individually
    killable so each test composes the exact production outage combo."""

    def __init__(
        self,
        *,
        spot_error: Exception | None = None,
        em_hist_error: Exception | None = None,
        em_hist_frame: pd.DataFrame | None = None,
        tx_frame: pd.DataFrame | None = None,
        tx_error: Exception | None = None,
    ) -> None:
        self._spot_error = spot_error
        self._em_hist_error = em_hist_error
        self._em_hist_frame = em_hist_frame
        self._tx_frame = tx_frame
        self._tx_error = tx_error

    def stock_zh_a_spot_em(self) -> pd.DataFrame:
        if self._spot_error is not None:
            raise self._spot_error
        return _em_spot_frame()

    def stock_zh_a_hist(self, symbol: str, **kwargs: Any) -> pd.DataFrame:
        if self._em_hist_error is not None:
            raise self._em_hist_error
        if self._em_hist_frame is None:
            return pd.DataFrame()
        return self._em_hist_frame

    def stock_zh_a_hist_tx(self, **kwargs: Any) -> pd.DataFrame:
        if self._tx_error is not None:
            raise self._tx_error
        return self._tx_frame

    def stock_financial_analysis_indicator(self, symbol: str) -> pd.DataFrame:
        # datacenter-web is healthy in every scenario here — financials
        # must keep flowing no matter how dark the price sources go.
        return pd.DataFrame([{"净资产收益率": 10.0}])


def _install_fake_ak(monkeypatch: pytest.MonkeyPatch, fake: _OutageAk) -> None:
    module = types.ModuleType("akshare")
    module.stock_zh_a_spot_em = fake.stock_zh_a_spot_em  # type: ignore[attr-defined]
    module.stock_zh_a_hist = fake.stock_zh_a_hist  # type: ignore[attr-defined]
    module.stock_zh_a_hist_tx = fake.stock_zh_a_hist_tx  # type: ignore[attr-defined]
    module.stock_financial_analysis_indicator = (  # type: ignore[attr-defined]
        fake.stock_financial_analysis_indicator
    )
    monkeypatch.setitem(sys.modules, "akshare", module)


class _FakeResponse:
    """requests.Response stand-in: status code + raw bytes content."""

    def __init__(self, *, status_code: int = 200, content: bytes = b"") -> None:
        self.status_code = status_code
        self.content = content


class _RecorderGet:
    """Stands in for requests.get; records every call."""

    def __init__(self, *, response: Any = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._response = response

    def __call__(self, url: str, **kwargs: Any) -> Any:
        self.calls.append({"url": url, **kwargs})
        return self._response


async def _run(monkeypatch: pytest.MonkeyPatch, fake: _OutageAk, symbols: list[str]):
    _install_fake_ak(monkeypatch, fake)
    agent = AkShareDataAgent("akshare_data")
    agent.llm = None
    return await agent.execute({"symbols": symbols})


class TestEmSpotBlackout:
    async def test_em_spot_dead_falls_back_to_tencent_spot_table(self, monkeypatch) -> None:
        """The production failure shape: EM push2 drops the connection and
        Tencent's batch quote serves the same table — the sliced quote
        carries the production-anchored values, history keeps flowing
        through the healthy EM seam, one GET serves the whole run."""
        fake = _OutageAk(
            spot_error=http.client.RemoteDisconnected(
                "Remote end closed connection without response"
            ),
            em_hist_frame=_em_hist_frame(),
        )
        _install_fake_ak(monkeypatch, fake)
        body = b"\n".join(
            [
                _tx_quote_line(
                    "sh600000",
                    "浦发银行",
                    "600000",
                    "9.16",
                    "9.00",
                    "9.03",
                    "1184853",
                    "9.18",
                    "9.00",
                    "108085",
                ),
                _tx_quote_line(
                    "sz000001",
                    "平安银行",
                    "000001",
                    "10.50",
                    "10.30",
                    "10.40",
                    "900000",
                    "10.60",
                    "10.30",
                    "94000",
                ),
            ]
        )
        recorder = _RecorderGet(response=_FakeResponse(content=body))
        monkeypatch.setattr(tencent_spot_mod.requests, "get", recorder)

        agent = AkShareDataAgent("akshare_data")
        agent.llm = None
        result = await agent.execute({"symbols": ["600000", "000001"]})

        # One batch quote round-trip for the whole run, symbol count aside.
        assert len(recorder.calls) == 1
        quote = result["market_data"]["600000"]
        assert quote["symbol"] == "600000"
        assert quote["current_price"] == pytest.approx(9.16)
        assert quote["previous_close"] == pytest.approx(9.00)
        assert quote["change"] == pytest.approx(0.16)
        assert quote["change_percent"] == pytest.approx(1.7777778)
        assert quote["volume"] == 1184853
        assert quote["amount"] == pytest.approx(1_080_850_000.0)
        assert quote["amplitude"] == pytest.approx(2.0)
        assert quote["high"] == pytest.approx(9.18)
        assert quote["low"] == pytest.approx(9.00)
        assert quote["open"] == pytest.approx(9.03)
        # History attaches through the healthy EM history seam.
        assert quote["historical_data"]["close"] == [1620.0, 1640.0, 1660.0]
        assert quote["as_of"] == "2026-09-24"
        # The second symbol rides the same single table.
        assert result["market_data"]["000001"]["current_price"] == pytest.approx(10.50)

    async def test_spot_double_blackout_derives_stock_info_from_closes(self, monkeypatch) -> None:
        """EM spot AND Tencent quote both dark, kline alive: history now
        runs outside the spot gate and a minimal stock_info is derived
        from the last two closes — before, stock_info None swallowed the
        whole symbol."""
        fake = _OutageAk(
            spot_error=http.client.RemoteDisconnected("EM spot drop"),
            em_hist_error=ConnectionError("EM hist drop"),
            tx_frame=_tx_hist_frame(),
        )
        recorder = _RecorderGet(response=_FakeResponse(status_code=500))
        monkeypatch.setattr(tencent_spot_mod.requests, "get", recorder)

        result = await _run(monkeypatch, fake, ["600519"])

        mkt = result["market_data"]["600519"]
        # Minimal quote derived from the closes — the same derivation the
        # ReAct fetcher's _akshare_cn uses; spot-only keys stay absent.
        assert mkt["symbol"] == "600519"
        assert mkt["current_price"] == 1660.0
        assert mkt["previous_close"] == 1640.0
        assert mkt["change"] == pytest.approx(20.0)
        assert mkt["change_percent"] == pytest.approx(20.0 / 1640.0 * 100)
        assert mkt["historical_data"]["close"] == [1620.0, 1640.0, 1660.0]
        assert mkt["as_of"] == "2026-09-24"
        assert set(mkt) == {
            "symbol",
            "current_price",
            "previous_close",
            "change",
            "change_percent",
            "historical_data",
            "as_of",
            "timestamp",
        }

    async def test_healthy_em_spot_bit_for_bit_unchanged(self, monkeypatch) -> None:
        """EM healthy means the fallback must not even be attempted — the
        result is the EM spot row plus EM bars, unchanged."""
        fake = _OutageAk(em_hist_frame=_em_hist_frame())
        _install_fake_ak(monkeypatch, fake)

        def _must_not_run(*args: Any, **kwargs: Any):
            raise AssertionError("tencent spot fallback must not run when EM spot is healthy")

        monkeypatch.setattr(data_agent_mod, "tencent_cn_spot_table", _must_not_run)

        agent = AkShareDataAgent("akshare_data")
        agent.llm = None
        result = await agent.execute({"symbols": ["600519"]})

        mkt = result["market_data"]["600519"]
        assert mkt["symbol"] == "600519"
        assert mkt["current_price"] == 1650.0
        assert mkt["previous_close"] == 1630.5
        assert mkt["change"] == 19.5
        assert mkt["change_percent"] == 1.2
        assert mkt["volume"] == 25_000
        assert mkt["amount"] == pytest.approx(4.1e9)
        assert mkt["amplitude"] == 2.1
        assert mkt["high"] == 1660.0
        assert mkt["low"] == 1635.0
        assert mkt["open"] == 1640.0
        assert mkt["historical_data"]["close"] == [1620.0, 1640.0, 1660.0]
        assert mkt["as_of"] == "2026-09-24"
        assert "timestamp" in mkt

    async def test_total_price_blackout_keeps_financials(self, monkeypatch) -> None:
        """Every price source dark (EM spot, Tencent quote, EM history,
        Tencent kline) keeps the existing degradation: no market_data, and
        datacenter-web financials still collected for the fundamental
        stage."""
        fake = _OutageAk(
            spot_error=http.client.RemoteDisconnected("EM spot drop"),
            em_hist_error=ConnectionError("EM hist drop"),
            tx_error=ConnectionError("tx drop"),
        )
        recorder = _RecorderGet(response=_FakeResponse(status_code=503))
        monkeypatch.setattr(tencent_spot_mod.requests, "get", recorder)

        result = await _run(monkeypatch, fake, ["600519"])

        assert result["market_data"] == {}
        assert result["financial_data"]["600519"]["metrics"]["roe"] == pytest.approx(0.1)
