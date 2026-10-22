"""Provider-health wiring for the three unrecorded data-agent seams (iteration 206).

Recon verdict: news (yfinance + CN feed), the CN event calendar, and the US
quarterly EM fallback all feed production but never record
``record_provider_outcome`` — the /api/monitoring/data-sources snapshot
stays blind to exactly the seams the smoke harness proved load-bearing
(the EM quarterly fallback is the only lit US-trend leg on the production
host). These pins go through the real recording API: drive the seam, then
read ``provider_health_snapshot`` — no mock of the recording channel.

All stubs are offline; akshare is faked in ``sys.modules`` so the event
seam's inner import never executes the real (slow) module.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd
import pytest

import app.agents.data_agent as data_agent_mod
from app.agents.data_agent import DataCollectionAgent
from app.tools.data.provider_health import provider_health_snapshot, reset_provider_health

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


@pytest.fixture(autouse=True)
def _clean_counters():
    reset_provider_health()
    yield
    reset_provider_health()


def _make_agent() -> DataCollectionAgent:
    return DataCollectionAgent(name="data_collection")


def _state(provider: str) -> dict:
    return provider_health_snapshot()["providers"].get(provider)


class TestUsQuarterlySeamHealth:
    @pytest.mark.asyncio
    async def test_ok_when_em_returns_block(self, monkeypatch):
        block = {"income_statement": {"dates": ["2026-03-28"] * 4, "data": {}}}
        monkeypatch.setattr(data_agent_mod, "fetch_us_quarterly_income_em", lambda _s: block)

        result = await _make_agent()._fetch_us_quarterly_statements("AAPL")

        assert result is block
        state = _state("em-us-quarterly")
        assert state is not None, "seam must record under em-us-quarterly"
        assert state["ok"] == 1
        assert state["total_calls"] == 1
        assert state["last_ok_at"] is not None

    @pytest.mark.asyncio
    async def test_fail_when_em_dark(self, monkeypatch):
        monkeypatch.setattr(data_agent_mod, "fetch_us_quarterly_income_em", lambda _s: None)

        result = await _make_agent()._fetch_us_quarterly_statements("AAPL")

        assert result is None
        state = _state("em-us-quarterly")
        assert state is not None
        assert state["fail"] == 1
        assert state["last_error"] is not None


class TestCnEventCalendarSeamHealth:
    def _fake_akshare(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace())

    @pytest.mark.asyncio
    async def test_ok_when_calendar_built(self, monkeypatch):
        self._fake_akshare(monkeypatch)
        calendar = {"events": [{"title": "e1"}, {"title": "e2"}, {"title": "e3"}]}
        monkeypatch.setattr(
            data_agent_mod, "build_event_calendar", lambda _s, akshare_module=None: calendar
        )

        result = await _make_agent()._fetch_cn_event_calendar("600000")

        assert result is calendar
        state = _state("akshare-cn-events")
        assert state is not None, "seam must record under akshare-cn-events"
        assert state["ok"] == 1
        assert state["last_error"] is None

    @pytest.mark.asyncio
    async def test_fail_when_calendar_unavailable(self, monkeypatch):
        self._fake_akshare(monkeypatch)
        monkeypatch.setattr(
            data_agent_mod, "build_event_calendar", lambda _s, akshare_module=None: None
        )

        result = await _make_agent()._fetch_cn_event_calendar("600000")

        assert result is None
        state = _state("akshare-cn-events")
        assert state is not None
        assert state["fail"] == 1

    @pytest.mark.asyncio
    async def test_fail_records_exception_type(self, monkeypatch):
        self._fake_akshare(monkeypatch)

        def _boom(_s, akshare_module=None):
            raise RuntimeError("endpoint dark")

        monkeypatch.setattr(data_agent_mod, "build_event_calendar", _boom)

        result = await _make_agent()._fetch_cn_event_calendar("600000")

        assert result is None
        state = _state("akshare-cn-events")
        assert state is not None
        assert state["fail"] == 1
        assert "RuntimeError" in (state["last_error"] or "")


class TestNewsSeamHealth:
    @pytest.mark.asyncio
    async def test_yfinance_leg_ok_counts_articles(self, monkeypatch):
        monkeypatch.setattr(
            data_agent_mod, "_sync_fetch_news", lambda _y, _s: [{"title": "a"}, {"title": "b"}]
        )

        articles = await _make_agent()._fetch_news("AAPL")

        assert len(articles) == 2
        state = _state("yfinance-news")
        assert state is not None, "yfinance news leg must record under yfinance-news"
        assert state["ok"] == 1

    @pytest.mark.asyncio
    async def test_yfinance_leg_fail_on_exception(self, monkeypatch):
        def _boom(_y, _s):
            raise ConnectionError("yahoo dark")

        monkeypatch.setattr(data_agent_mod, "_sync_fetch_news", _boom)

        articles = await _make_agent()._fetch_news("AAPL")

        assert articles == []
        state = _state("yfinance-news")
        assert state is not None
        assert state["fail"] == 1
        assert "ConnectionError" in (state["last_error"] or "")

    @pytest.mark.asyncio
    async def test_cn_leg_ok_counts_articles(self, monkeypatch):
        monkeypatch.setattr(data_agent_mod, "_sync_fetch_news", lambda _y, _s: [])
        monkeypatch.setattr(
            data_agent_mod,
            "fetch_cn_news",
            lambda _s: [{"title": "c1"}, {"title": "c2"}, {"title": "c3"}],
        )

        articles = await _make_agent()._fetch_news("600000")

        assert len(articles) == 3
        state = _state("em-news-cn")
        assert state is not None, "CN news leg must record under em-news-cn"
        assert state["ok"] == 1

    @pytest.mark.asyncio
    async def test_cn_leg_fail_when_feed_dark(self, monkeypatch):
        monkeypatch.setattr(data_agent_mod, "_sync_fetch_news", lambda _y, _s: [])
        monkeypatch.setattr(data_agent_mod, "fetch_cn_news", lambda _s: None)

        articles = await _make_agent()._fetch_news("600000")

        assert articles == []
        state = _state("em-news-cn")
        assert state is not None
        assert state["fail"] == 1


class TestAkshareHistorySeamHealth:
    """The agent-level CN history path (the production pipeline's leg):
    the East Money primary recorded nothing — success, empty frame, and
    exception were all invisible, so on the production host (push2his
    domain-blocked since 2026-09-27) only the Tencent fallback ever showed
    in provider-health and the primary's persistent outage was unreadable.
    Same seam name as fetch_historical's CN branch — same upstream
    provider, the iteration-101 one-name-two-call-sites precedent."""

    def _em_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "日期": "2026-09-22",
                    "开盘": 1600.0,
                    "最高": 1625.0,
                    "最低": 1595.0,
                    "收盘": 1620.0,
                    "成交量": 24_000,
                    "成交额": 3.9e9,
                }
            ]
        )

    def _tx_frame(self) -> pd.DataFrame:
        # English columns, volume in shares — exactly as stock_zh_a_hist_tx
        # answers; the shared fallback mapper renames and rescales.
        return pd.DataFrame(
            [
                {
                    "date": "2026-09-22",
                    "open": 1600.0,
                    "close": 1620.0,
                    "high": 1625.0,
                    "low": 1595.0,
                    "volume": 2_400_000,
                    "amount": 3.9e9,
                }
            ]
        )

    def _ak(self, *, em_frame=None, em_raises=None, tx_frame=None) -> SimpleNamespace:
        def _em(**_kwargs):
            if em_raises is not None:
                raise em_raises
            return em_frame

        def _tx(**_kwargs):
            if tx_frame is None:
                raise AssertionError("tencent must not run")
            return tx_frame

        return SimpleNamespace(stock_zh_a_hist=_em, stock_zh_a_hist_tx=_tx)

    def test_em_ok_records_ok_and_never_tencent(self) -> None:
        result = data_agent_mod._sync_fetch_akshare_history(
            "600519", self._ak(em_frame=self._em_frame())
        )

        assert result is not None and result["close"] == [1620.0]
        assert "amount" in result
        state = _state("akshare-cn-hist")
        assert state is not None, "EM primary leg must record"
        assert state["ok"] == 1 and state["last_error"] is None
        assert _state("tencent-cn-hist") is None  # healthy primary → no fallback record

    def test_em_dark_records_fail_and_tencent_catches(self) -> None:
        ak = self._ak(em_raises=ConnectionError("TCP dropped"), tx_frame=self._tx_frame())

        result = data_agent_mod._sync_fetch_akshare_history("600519", ak)

        assert result is not None  # fallback supplied the bars
        state = _state("akshare-cn-hist")
        assert state is not None and state["fail"] == 1
        assert "ConnectionError" in state["last_error"]
        assert _state("tencent-cn-hist")["ok"] == 1

    def test_em_empty_frame_records_fail(self) -> None:
        ak = self._ak(em_frame=pd.DataFrame(), tx_frame=self._tx_frame())

        result = data_agent_mod._sync_fetch_akshare_history("600519", ak)

        assert result is not None
        state = _state("akshare-cn-hist")
        assert state is not None and state["fail"] == 1
        assert "empty" in state["last_error"]
        assert _state("tencent-cn-hist")["ok"] == 1

    def test_both_dead_records_both_fails(self) -> None:
        ak = SimpleNamespace(
            stock_zh_a_hist=self._ak(em_raises=ConnectionError("dark")).stock_zh_a_hist,
            stock_zh_a_hist_tx=lambda **_k: None,
        )

        result = data_agent_mod._sync_fetch_akshare_history("600519", ak)

        assert result is None  # pre-existing degradation unchanged
        assert _state("akshare-cn-hist")["fail"] == 1
        assert _state("tencent-cn-hist")["fail"] == 1
