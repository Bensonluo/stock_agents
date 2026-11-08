"""FINNHUB_ENABLED: from dead flag to real toggle (iteration 218).

Recon verdict: declared in Settings and documented in .env.example since the
beginning, but no code ever read it — setting FINNHUB_ENABLED=false silently
kept full finnhub behavior. Every finnhub network call funnels through the
single choke point ``_finnhub_get`` (quote/profile/metric, company news, the
consensus recommendation leg, and the paid-tier candle probe), so the master
gate lives there — plus the two seams whose local control flow would turn a
disabled leg into a *recorded* provider failure: ``fetch_us_news`` records
"feed returned nothing" on an empty fetch, and the consensus seam's ``elif``
records a fail whenever a key is configured. Config-off is a no-op, not a
provider failure (the no-API-key house rule) — nothing may appear in
provider-health even with a key set. The enabled controls pin that the
default keeps every path live.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.tools.data.consensus as consensus_mod
import app.tools.data.fetcher_finnhub as fetcher_finnhub_mod
from app.tools.data.consensus import _sync_fetch_us_raw
from app.tools.data.fetcher_finnhub import (
    _finnhub_fetch,
    _finnhub_get,
    _finnhub_historical,
    fetch_us_news,
)
from app.tools.data.provider_health import provider_health_snapshot, reset_provider_health

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


@pytest.fixture(autouse=True)
def _clean_counters():
    reset_provider_health()
    yield
    reset_provider_health()


def _flag(monkeypatch, *, enabled: bool) -> None:
    ns = SimpleNamespace(finnhub_enabled=enabled, finnhub_api_key="key")
    monkeypatch.setattr(fetcher_finnhub_mod, "get_settings", lambda: ns)
    monkeypatch.setattr(consensus_mod, "get_settings", lambda: ns)


def _state(provider: str) -> dict | None:
    return provider_health_snapshot()["providers"].get(provider)


def _bomb(*_args, **_kwargs):
    raise AssertionError("finnhub leg must not run with FINNHUB_ENABLED=false")


class TestGetChokePoint:
    def test_off_returns_none_without_http(self, monkeypatch):
        # A hit-marker, not a bomb: _finnhub_get swallows exceptions from
        # requests.get, so a raising stub would pass vacuously via the
        # except branch. The pin must observe that HTTP is never attempted.
        _flag(monkeypatch, enabled=False)
        seen = {}

        def _mark(*_args, **_kwargs):
            seen["hit"] = True
            return SimpleNamespace(
                status_code=200,
                raise_for_status=lambda: None,
                json=lambda: {"c": 1.0},
            )

        monkeypatch.setattr(fetcher_finnhub_mod.requests, "get", _mark)

        assert _finnhub_get("/quote", {"symbol": "AAPL"}) is None
        assert "hit" not in seen

    def test_enabled_still_sends_token(self, monkeypatch):
        _flag(monkeypatch, enabled=True)
        seen = {}

        def _fake_get(_url, params=None, timeout=None):
            seen["params"] = params
            return SimpleNamespace(
                status_code=200,
                raise_for_status=lambda: None,
                json=lambda: {"c": 1.0},
            )

        monkeypatch.setattr(fetcher_finnhub_mod.requests, "get", _fake_get)

        assert _finnhub_get("/quote", {"symbol": "AAPL"}) == {"c": 1.0}
        assert seen["params"]["token"] == "key"


class TestSnapshotLeg:
    @pytest.mark.asyncio
    async def test_off_returns_none_before_any_network(self, monkeypatch):
        _flag(monkeypatch, enabled=False)
        monkeypatch.setattr(fetcher_finnhub_mod, "_finnhub_get", _bomb)

        assert await _finnhub_fetch("AAPL") is None


class TestUsNewsLeg:
    @pytest.mark.asyncio
    async def test_off_returns_empty_and_records_nothing(self, monkeypatch):
        _flag(monkeypatch, enabled=False)
        monkeypatch.setattr(fetcher_finnhub_mod, "_finnhub_get", _bomb)

        assert await fetch_us_news("AAPL") == []
        assert _state("finnhub-news") is None  # config-off records nothing

    @pytest.mark.asyncio
    async def test_enabled_keeps_news_path_live(self, monkeypatch):
        _flag(monkeypatch, enabled=True)
        items = [{"headline": "Fed cuts rates", "datetime": 1700000000, "source": "Reuters"}]
        monkeypatch.setattr(fetcher_finnhub_mod, "_finnhub_get", lambda _path, _params: items)

        articles = await fetch_us_news("AAPL")

        assert len(articles) == 1 and articles[0]["original_symbol"] == "AAPL"
        state = _state("finnhub-news")
        assert state is not None and state["ok"] == 1


class TestHistoricalLeg:
    @pytest.mark.asyncio
    async def test_off_returns_none_before_any_network(self, monkeypatch):
        _flag(monkeypatch, enabled=False)
        monkeypatch.setattr(fetcher_finnhub_mod, "_finnhub_get", _bomb)

        assert await _finnhub_historical("AAPL", "1y") is None


class TestRecommendationSeam:
    def test_off_records_nothing(self, monkeypatch):
        # The recommendation seam records a fail on a None fetch whenever a
        # key is configured — the gate must keep a toggled-off leg from
        # reaching the health counters even with FINNHUB_API_KEY present.
        _flag(monkeypatch, enabled=False)
        monkeypatch.setattr(fetcher_finnhub_mod.requests, "get", _bomb)

        assert _sync_fetch_us_raw("AAPL") is None
        assert _state("finnhub-recommendation") is None
