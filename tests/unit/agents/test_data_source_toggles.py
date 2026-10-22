"""AKSHARE_ENABLED: from dead flag to real toggle (iteration 217).

Recon verdict: the flag has been declared in Settings and documented in
CLAUDE.md / .env.example since the beginning, but no code ever read it —
setting AKSHARE_ENABLED=false silently kept full akshare behavior. These
pins drive the three akshare entry points in the collection layer with the
flag off: each must no-op BEFORE touching akshare. Config-off is a no-op,
not a provider failure (the no-API-key house rule) — nothing may appear in
provider-health. The enabled controls pin that the default keeps every
collection path live.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

import app.agents.data_agent as data_agent_mod
from app.agents.data_agent import AkShareDataAgent, DataCollectionAgent
from app.tools.data.provider_health import provider_health_snapshot, reset_provider_health

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


@pytest.fixture(autouse=True)
def _clean_counters():
    reset_provider_health()
    yield
    reset_provider_health()


def _flag(monkeypatch, *, enabled: bool) -> None:
    monkeypatch.setattr(
        data_agent_mod, "get_settings", lambda: SimpleNamespace(akshare_enabled=enabled)
    )


def _fake_akshare(monkeypatch) -> None:
    # Import-proof stub: `import akshare` resolves instantly and offline.
    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace())


def _state(provider: str) -> dict:
    return provider_health_snapshot()["providers"].get(provider)


def _bomb(*_args, **_kwargs):
    raise AssertionError("akshare leg must not run with AKSHARE_ENABLED=false")


class TestAkshareAgentToggle:
    @pytest.mark.asyncio
    async def test_off_returns_empty_and_never_collects(self, monkeypatch):
        _flag(monkeypatch, enabled=False)
        _fake_akshare(monkeypatch)
        monkeypatch.setattr(AkShareDataAgent, "_fetch_akshare_spot_table", _bomb)

        result = await AkShareDataAgent(name="akshare_data").execute({"symbols": ["600519"]})

        assert result == {"market_data": {}, "financial_data": {}}
        assert provider_health_snapshot()["providers"] == {}  # config-off records nothing

    @pytest.mark.asyncio
    async def test_enabled_default_keeps_collection_live(self, monkeypatch):
        _flag(monkeypatch, enabled=True)
        _fake_akshare(monkeypatch)

        async def _spot(self, ak, syms):
            return None

        monkeypatch.setattr(AkShareDataAgent, "_fetch_akshare_spot_table", _spot)

        async def _no_spot(self, symbol, spot_df):
            return None  # forces the derive-from-closes path

        async def _hist(self, symbol, ak):
            return {"dates": ["2026-09-22"], "close": [1620.0]}

        async def _fin(self, symbol, ak):
            return {"symbol": symbol, "metrics": {}}

        monkeypatch.setattr(AkShareDataAgent, "_fetch_akshare_stock_info", _no_spot)
        monkeypatch.setattr(AkShareDataAgent, "_fetch_akshare_history", _hist)
        monkeypatch.setattr(AkShareDataAgent, "_fetch_akshare_financials", _fin)

        result = await AkShareDataAgent(name="akshare_data").execute({"symbols": ["600519"]})

        assert result["market_data"]["600519"]["current_price"] == 1620.0
        assert result["financial_data"]["600519"] == {"symbol": "600519", "metrics": {}}


class TestCnEventCalendarToggle:
    @pytest.mark.asyncio
    async def test_off_skips_calendar_before_akshare(self, monkeypatch):
        _flag(monkeypatch, enabled=False)
        _fake_akshare(monkeypatch)
        monkeypatch.setattr(data_agent_mod, "build_event_calendar", _bomb)

        result = await DataCollectionAgent(name="data_collection")._fetch_cn_event_calendar(
            "600000"
        )

        assert result is None
        assert _state("akshare-cn-events") is None  # no-op, not a provider failure


class TestCnNewsToggle:
    @pytest.mark.asyncio
    async def test_off_skips_cn_leg(self, monkeypatch):
        _flag(monkeypatch, enabled=False)
        monkeypatch.setattr(data_agent_mod, "_sync_fetch_news", lambda _y, _s: [{"title": "a"}])
        monkeypatch.setattr(data_agent_mod, "fetch_cn_news", _bomb)

        articles = await DataCollectionAgent(name="data_collection")._fetch_news("600000")

        assert articles == [{"title": "a"}]  # yfinance result untouched
        assert _state("em-news-cn") is None

    @pytest.mark.asyncio
    async def test_enabled_keeps_cn_leg(self, monkeypatch):
        _flag(monkeypatch, enabled=True)
        monkeypatch.setattr(data_agent_mod, "_sync_fetch_news", lambda _y, _s: [{"title": "a"}])
        monkeypatch.setattr(
            data_agent_mod, "fetch_cn_news", lambda _s: [{"title": "c1"}, {"title": "c2"}]
        )

        articles = await DataCollectionAgent(name="data_collection")._fetch_news("600000")

        assert len(articles) == 3
        state = _state("em-news-cn")
        assert state is not None and state["ok"] == 1
