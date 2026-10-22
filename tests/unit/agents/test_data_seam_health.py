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
