"""Integration coverage for Finnhub cache gates and provider-chain fallbacks."""

import sys
from types import SimpleNamespace

import pandas as pd
import pytest

import app.tools.data.consensus as consensus
import app.tools.data.fetcher as fetcher
import app.tools.data.fetcher_finnhub as finnhub
from app.config import get_settings
from app.tools.data.provider_health import provider_health_snapshot, reset_provider_health


@pytest.fixture(autouse=True)
def _state(monkeypatch):
    monkeypatch.setattr(get_settings(), "finnhub_api_key", "test-key")
    monkeypatch.setattr(get_settings(), "finnhub_enabled", False)
    fetcher._cache.clear()
    reset_provider_health()
    yield
    fetcher._cache.clear()
    reset_provider_health()


def test_enabled_http_helper_requires_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "finnhub_enabled", True)
    monkeypatch.setattr(get_settings(), "finnhub_api_key", None)
    calls = []

    def _request(url, **kwargs):
        calls.append(kwargs["params"])
        return SimpleNamespace(
            status_code=200, raise_for_status=lambda: None, json=lambda: {"c": 123}
        )

    monkeypatch.setattr(finnhub.requests, "get", _request)

    assert finnhub._finnhub_get("/quote", {"symbol": "AAPL"}) is None
    assert calls == []


@pytest.mark.asyncio
async def test_enabled_snapshot_and_history_collect_normally(monkeypatch):
    monkeypatch.setattr(get_settings(), "finnhub_enabled", True)
    calls = []
    responses = {
        "/quote": {"c": 123.0},
        "/stock/profile2": {"name": "Apple"},
        "/stock/metric": {"metric": {"beta": 1.2}},
        "/company-news": [{"headline": "Test news"}],
        "/stock/candle": {"s": "ok", "t": [1792627200], "c": [123.0]},
    }

    def _get(path, params):
        calls.append(path)
        return responses[path]

    monkeypatch.setattr(finnhub, "_finnhub_get", _get)

    snapshot = await finnhub._finnhub_fetch("AAPL")
    history = await finnhub._finnhub_historical("AAPL", "1y")

    assert snapshot["market_data"]["current_price"] == 123.0
    assert snapshot["financial_data"]["metrics"]["beta"] == 1.2
    assert len(snapshot["news_data"]) == 1
    assert history["close"] == [123.0]
    assert sorted(calls) == sorted(responses)


@pytest.mark.asyncio
@pytest.mark.parametrize("warm_cache", [False, True])
async def test_disabled_consensus_skips_fetch_and_cached_annotation(monkeypatch, warm_cache):
    if warm_cache:
        fetcher._cache_set("consensus_us_raw:AAPL", [{"period": "2026-10-01", "buy": 3}])

    def _unexpected(*args):
        pytest.fail("disabled consensus must not collect")

    monkeypatch.setattr(consensus, "_sync_fetch_us_raw", _unexpected)

    assert await consensus.fetch_us_consensus("AAPL") is None
    assert provider_health_snapshot()["providers"] == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_snapshot_chain_skips_disabled_provider_and_uses_next(monkeypatch, enabled):
    monkeypatch.setattr(get_settings(), "finnhub_enabled", enabled)
    calls = []

    async def _miss(symbol):
        return None

    async def _priced(symbol):
        return {"market_data": {"symbol": symbol, "current_price": 123.0}}

    async def _finnhub(symbol):
        calls.append(symbol)
        return {"market_data": {"symbol": symbol, "current_price": 456.0}}

    async def _sleep(_seconds):
        pass

    monkeypatch.setattr(fetcher, "_yfinance_fetch", _miss)
    monkeypatch.setattr(fetcher, "_alphavantage_fetch", _miss)
    monkeypatch.setattr(fetcher, "_finnhub_fetch", _finnhub)
    monkeypatch.setattr(fetcher, "_akshare_fetch", _priced)
    monkeypatch.setattr(fetcher.asyncio, "sleep", _sleep)

    result = await fetcher.fetch_stock_data("AAPL")

    assert result["market_data"]["current_price"] == (456.0 if enabled else 123.0)
    assert calls == (["AAPL"] if enabled else [])
    providers = provider_health_snapshot()["providers"]
    assert ("finnhub" in providers) is enabled
    assert providers["finnhub" if enabled else "akshare"]["ok"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_history_chain_skips_disabled_provider_and_uses_next(monkeypatch, enabled):
    monkeypatch.setattr(get_settings(), "finnhub_enabled", enabled)
    monkeypatch.setattr(get_settings(), "alpha_vantage_key", None)
    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        SimpleNamespace(
            Ticker=lambda symbol: SimpleNamespace(history=lambda **kwargs: pd.DataFrame())
        ),
    )
    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace())
    calls = []
    history = {"dates": ["2026-10-22"], "close": [123.0]}

    async def _finnhub(symbol, period):
        calls.append(symbol)
        return {"symbol": symbol, "period": period, **history, "close": [456.0]}

    async def _sina(symbol, period):
        return history

    monkeypatch.setattr(fetcher, "_finnhub_historical", _finnhub)
    monkeypatch.setattr(fetcher, "_sina_us_hist", _sina)

    result = await fetcher.fetch_historical("AAPL", "1y")

    assert result["close"] == ([456.0] if enabled else [123.0])
    assert calls == (["AAPL"] if enabled else [])
    providers = provider_health_snapshot()["providers"]
    assert ("finnhub-hist" in providers) is enabled
    assert providers["finnhub-hist" if enabled else "sina-us-hist"]["ok"] == 1


@pytest.mark.asyncio
async def test_reenabled_news_and_consensus_collect_normally(monkeypatch):
    monkeypatch.setattr(get_settings(), "finnhub_enabled", True)
    monkeypatch.setattr(finnhub, "_finnhub_get", lambda *args: [{"headline": "Test news"}])
    monkeypatch.setattr(
        consensus, "_finnhub_get", lambda *args: [{"period": "2026-10-01", "buy": 3}]
    )

    assert len(await finnhub.fetch_us_news("AAPL")) == 1
    assert (await consensus.fetch_us_consensus("AAPL"))["ratings"]["total"] == 3
    providers = provider_health_snapshot()["providers"]
    assert providers["finnhub-news"]["ok"] == 1
    assert providers["finnhub-recommendation"]["ok"] == 1
