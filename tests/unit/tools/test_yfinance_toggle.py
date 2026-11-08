"""YFINANCE_ENABLED: from dead flag to real toggle (iteration 220).

Recon verdict: the last of the three declared-but-unread toggles (akshare
wired in 217, finnhub in 218). Unlike finnhub's single choke point, yfinance
attempts span seven call sites in four modules — but every one is a *first
leg* with an existing fallback chain behind it (provider chain / AV /
Tencent / Sina / East Money). Each gate turns the attempt into its native
miss value (None / {} / []) so the fallback chain serves, mirroring a
yfinance outage bit-for-bit; config-off records nothing in provider-health
(the no-API-key house rule).

Pin discipline: every gated site lives inside a broad ``except Exception``
that swallows raising stubs — so every must-not-run pin uses a call-COUNTER
poison (``calls`` must stay empty), never an exception bomb (the lesson
from iteration 218's vacuous-green choke-point pin).
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

import app.agents.data_agent as data_agent_mod
import app.services.backtest_service as backtest_mod
import app.tools.data.fetcher as fetcher_mod
import app.tools.data.fetcher_benchmarks as bench_mod
import app.tools.data.fetcher_yfinance as yf_mod
from app.agents.data_agent import DataCollectionAgent
from app.tools.data.fetcher import fetch_historical
from app.tools.data.fetcher_benchmarks import _sync_fetch_benchmark_history
from app.tools.data.fetcher_yfinance import _yfinance_fetch
from app.tools.data.provider_health import provider_health_snapshot, reset_provider_health

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


@pytest.fixture(autouse=True)
def _clean_counters():
    reset_provider_health()
    yield
    reset_provider_health()


def _state(provider: str) -> dict | None:
    return provider_health_snapshot()["providers"].get(provider)


def _ticker_poison(calls: list) -> SimpleNamespace:
    """yfinance module fake whose Ticker records the attempt then raises.

    The raise is swallowed by every site's broad except — the observable is
    the call list, which must stay empty when the toggle is off.
    """

    def _ticker(symbol):
        calls.append(symbol)
        raise RuntimeError("poisoned yfinance")

    return SimpleNamespace(Ticker=_ticker)


class TestHistoryChain:
    @pytest.mark.asyncio
    async def test_off_skips_yfinance_leg_and_falls_to_us_tail(self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(
            fetcher_mod,
            "get_settings",
            lambda: SimpleNamespace(
                yfinance_enabled=False,
                finnhub_enabled=True,
                finnhub_api_key=None,
                alpha_vantage_key=None,
            ),
        )
        monkeypatch.setitem(sys.modules, "yfinance", _ticker_poison(calls))

        async def _sina(symbol, period):
            return {"dates": ["2026-01-02"], "close": [1.0]}

        monkeypatch.setattr(fetcher_mod, "_sina_us_hist", _sina)

        result = await fetch_historical("ZZZZ", "2y")

        assert calls == []  # no yfinance attempt
        assert result is not None and result["dates"] == ["2026-01-02"]
        assert _state("yfinance-hist") is None  # config-off records nothing


class TestSnapshotProvider:
    @pytest.mark.asyncio
    async def test_off_returns_none_before_any_thread(self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(
            yf_mod,
            "get_settings",
            lambda: SimpleNamespace(yfinance_enabled=False),
            raising=False,
        )
        monkeypatch.setitem(sys.modules, "yfinance", _ticker_poison(calls))

        assert await _yfinance_fetch("AAPL") is None
        assert calls == []


class TestBenchmarkLeg:
    def test_off_goes_straight_to_tencent_without_yfinance(self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(
            bench_mod,
            "get_settings",
            lambda: SimpleNamespace(yfinance_enabled=False),
            raising=False,
        )
        monkeypatch.setitem(sys.modules, "yfinance", _ticker_poison(calls))
        sentinel = {"symbol": "XLF", "dates": ["2026-01-02"], "close": [100.0]}
        monkeypatch.setattr(bench_mod, "tencent_index_history", lambda _s: sentinel)

        result = _sync_fetch_benchmark_history("XLF")

        assert calls == []
        assert result is sentinel
        assert _state("yfinance-benchmark") is None
        tencent = _state("tencent-benchmark")
        assert tencent is not None and tencent["ok"] == 1

    def test_enabled_keeps_yfinance_first_leg(self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(
            bench_mod,
            "get_settings",
            lambda: SimpleNamespace(yfinance_enabled=True),
            raising=False,
        )
        monkeypatch.setitem(sys.modules, "yfinance", _ticker_poison(calls))
        sentinel = {"symbol": "XLF", "dates": ["2026-01-02"], "close": [100.0]}
        monkeypatch.setattr(bench_mod, "tencent_index_history", lambda _s: sentinel)

        result = _sync_fetch_benchmark_history("XLF")

        assert calls == ["XLF"]  # attempted first, poison = dark yfinance
        assert result is sentinel  # Tencent fallback still serves
        yf_state = _state("yfinance-benchmark")
        assert yf_state is not None and yf_state["fail"] == 1


class TestAgentLegs:
    def test_off_market_data_returns_empty(self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(
            data_agent_mod,
            "get_settings",
            lambda: SimpleNamespace(yfinance_enabled=False, akshare_enabled=True),
        )
        monkeypatch.setattr(data_agent_mod, "yf", _ticker_poison(calls))

        result = data_agent_mod._sync_fetch_market_data("AAPL", "AAPL", lambda _h: {})

        assert result == {}
        assert calls == []

    def test_off_financial_data_returns_empty(self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(
            data_agent_mod,
            "get_settings",
            lambda: SimpleNamespace(yfinance_enabled=False, akshare_enabled=True),
        )
        monkeypatch.setattr(data_agent_mod, "yf", _ticker_poison(calls))

        result = data_agent_mod._sync_fetch_financial_data("AAPL", "AAPL", lambda _q: {})

        assert result == {}
        assert calls == []

    @pytest.mark.asyncio
    async def test_off_news_skips_yfinance_leg(self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(
            data_agent_mod,
            "get_settings",
            lambda: SimpleNamespace(yfinance_enabled=False, akshare_enabled=False),
        )
        monkeypatch.setattr(data_agent_mod, "_sync_fetch_news", lambda *_a: calls.append("x"))

        articles = await DataCollectionAgent(name="data_collection")._fetch_news("AAPL")

        assert articles == []
        assert calls == []  # to_thread never reached the sync fetcher
        assert _state("yfinance-news") is None

    @pytest.mark.asyncio
    async def test_enabled_keeps_news_leg(self, monkeypatch):
        monkeypatch.setattr(
            data_agent_mod,
            "get_settings",
            lambda: SimpleNamespace(yfinance_enabled=True, akshare_enabled=False),
        )
        monkeypatch.setattr(data_agent_mod, "_sync_fetch_news", lambda _y, _s: [{"title": "a"}])

        articles = await DataCollectionAgent(name="data_collection")._fetch_news("AAPL")

        assert articles == [{"title": "a"}]
        state = _state("yfinance-news")
        assert state is not None and state["ok"] == 1


class TestBacktestLeg:
    @pytest.mark.asyncio
    async def test_off_goes_straight_to_provider_chain(self, monkeypatch):
        calls: list = []
        # backtest_service reads the settings object directly (its house
        # idiom), not the get_settings callable
        monkeypatch.setattr(backtest_mod, "settings", SimpleNamespace(yfinance_enabled=False))
        monkeypatch.setattr(backtest_mod, "yf", _ticker_poison(calls))

        async def _chain(_symbol, _start, _end):
            return "CHAIN"

        fake_self = SimpleNamespace(_fetch_data_via_chain=_chain)

        result = await backtest_mod.BacktestService._fetch_data(
            fake_self, "AAPL", "2026-01-01", "2026-01-02"
        )

        assert result == "CHAIN"
        assert calls == []  # no direct yfinance attempt
