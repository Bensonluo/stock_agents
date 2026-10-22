"""Provider-health records at the data chain's key fallback seams.

Outcome tracking is a pure side-channel: it must record the outcome the
chain actually produced — primary fail + fallback ok when the fallback
caught an outage, primary ok and NO fallback record when the fallback was
never called — without changing any return value or exception path. These
tests drive the real seams offline (fake akshare modules, monkeypatched
tencent fetches, dead yfinance) and read the resulting counter state.
"""

from __future__ import annotations

import sys
import types
from datetime import date
from typing import Any

import pandas as pd
import pytest
import requests

import app.agents.data_agent as data_agent_mod
import app.tools.data.fetcher as fetcher_mod
import app.tools.data.fetcher_benchmarks as fetcher_benchmarks_mod
import app.tools.data.fetcher_cn as fetcher_cn_mod
import app.tools.data.fetcher_finnhub as fetcher_finnhub_mod
from app.agents.data_agent import AkShareDataAgent
from app.config import get_settings
from app.tools.data.fetcher import fetch_us_news
from app.tools.data.provider_health import provider_health_snapshot, reset_provider_health

_DATES = ("2026-09-22", "2026-09-23", "2026-09-24")
_AMOUNTS_YUAN = (3.9e9, 4.1e9, 4.0e9)

_FAKE_FINANCIALS = {
    "symbol": "600519",
    "metrics": {"roe": 0.31, "trailing_eps": 64.0},
    "timestamp": "2026-09-28T00:00:00",
}


def _em_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "日期": d,
                "开盘": 1600.0 + i * 20.0,
                "收盘": 1620.0 + i * 20.0,
                "最高": 1625.0 + i * 20.0,
                "最低": 1595.0 + i * 20.0,
                "成交量": 24_000 + i * 500,
                "成交额": _AMOUNTS_YUAN[i],
            }
            for i, d in enumerate(_DATES)
        ]
    )


def _tx_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": date.fromisoformat(d),
                "open": 1600.0 + i * 20.0,
                "close": 1620.0 + i * 20.0,
                "high": 1625.0 + i * 20.0,
                "low": 1595.0 + i * 20.0,
                "volume": 2_400_000 + i * 100_000,
                "turnover": 0.5,
                "amount": _AMOUNTS_YUAN[i],
            }
            for i, d in enumerate(_DATES)
        ]
    )


class _RecorderAk:
    """Stands in for the akshare module; records every history call."""

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


def _install_ak(monkeypatch: pytest.MonkeyPatch, fake: _RecorderAk) -> None:
    module = types.ModuleType("akshare")
    module.stock_zh_a_hist = fake.stock_zh_a_hist  # type: ignore[attr-defined]
    module.stock_zh_a_hist_tx = fake.stock_zh_a_hist_tx  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "akshare", module)
    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=_DeadYf.Ticker))


@pytest.fixture(autouse=True)
def _clean_state():
    reset_provider_health()
    fetcher_mod._cache.clear()
    settings = get_settings()
    settings.finnhub_api_key = None
    settings.alpha_vantage_key = None
    yield
    reset_provider_health()
    fetcher_mod._cache.clear()


def _providers() -> dict[str, Any]:
    return provider_health_snapshot()["providers"]


class TestBenchmarkHistoryWiring:
    def _install_yf(self, monkeypatch: pytest.MonkeyPatch, *, healthy: bool) -> None:
        class _Ticker:
            def __init__(self, symbol: str) -> None:
                pass

            def history(self, **kwargs: Any) -> pd.DataFrame:
                if not healthy:
                    raise RuntimeError("Too Many Requests")
                index = pd.to_datetime(list(_DATES))
                return pd.DataFrame({"Close": [5100.0, 5110.0, 5120.0]}, index=index)

        monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=_Ticker))

    def test_healthy_yfinance_records_ok_and_never_tencent(self, monkeypatch) -> None:
        self._install_yf(monkeypatch, healthy=True)
        monkeypatch.setattr(
            fetcher_benchmarks_mod,
            "tencent_index_history",
            lambda symbol: pytest.fail("tencent must not be called"),
        )

        result = fetcher_mod._sync_fetch_benchmark_history("000001.SS")

        assert result is not None
        assert result["close"] == [5100.0, 5110.0, 5120.0]
        assert _providers() == {"yfinance-benchmark": _providers()["yfinance-benchmark"]}
        assert _providers()["yfinance-benchmark"]["ok"] == 1

    def test_dead_yfinance_records_fail_and_tencent_ok(self, monkeypatch) -> None:
        self._install_yf(monkeypatch, healthy=False)
        bench = {"symbol": "000001.SS", "dates": list(_DATES), "close": [5100.0, 5110.0, 5120.0]}
        monkeypatch.setattr(fetcher_benchmarks_mod, "tencent_index_history", lambda symbol: bench)

        result = fetcher_mod._sync_fetch_benchmark_history("000001.SS")

        assert result == bench  # the fallback's value passes through untouched
        providers = _providers()
        assert providers["yfinance-benchmark"]["fail"] == 1
        assert providers["yfinance-benchmark"]["ok"] == 0
        assert providers["tencent-benchmark"]["ok"] == 1

    def test_both_dead_records_both_fail(self, monkeypatch) -> None:
        self._install_yf(monkeypatch, healthy=False)
        monkeypatch.setattr(fetcher_benchmarks_mod, "tencent_index_history", lambda symbol: None)

        result = fetcher_mod._sync_fetch_benchmark_history("000001.SS")

        assert result is None  # pre-existing fail-uncached semantics
        providers = _providers()
        assert providers["yfinance-benchmark"]["fail"] == 1
        assert providers["tencent-benchmark"]["fail"] == 1


class TestAkshareCNSnapshotWiring:
    async def _run(self, monkeypatch: pytest.MonkeyPatch, fake: _RecorderAk) -> Any:
        monkeypatch.setattr(
            fetcher_cn_mod, "_sync_fetch_akshare_financials", lambda symbol, ak: _FAKE_FINANCIALS
        )
        return await fetcher_mod._akshare_cn("600519", fake)

    @pytest.mark.asyncio
    async def test_em_dead_tencent_catches_records_the_pair(self, monkeypatch) -> None:
        fake = _RecorderAk(em_error=ConnectionError("TCP dropped"), tx_frame=_tx_frame())

        result = await self._run(monkeypatch, fake)

        assert result is not None and result["market_data"]["current_price"] == 1660.0
        providers = _providers()
        assert providers["akshare-cn"]["fail"] == 1
        assert "ConnectionError" in providers["akshare-cn"]["last_error"]
        assert providers["tencent-cn-hist"]["ok"] == 1

    @pytest.mark.asyncio
    async def test_healthy_em_records_ok_and_never_tencent(self, monkeypatch) -> None:
        """A provider that was never called must never be recorded."""
        fake = _RecorderAk(em_frame=_em_frame(), tx_error=RuntimeError("must not run"))

        result = await self._run(monkeypatch, fake)

        assert result is not None and result["market_data"]["current_price"] == 1660.0
        providers = _providers()
        assert providers["akshare-cn"]["ok"] == 1
        assert "tencent-cn-hist" not in providers

    @pytest.mark.asyncio
    async def test_both_dead_records_both_fail(self, monkeypatch) -> None:
        fake = _RecorderAk(em_error=ConnectionError("EM drop"), tx_error=ConnectionError("tx drop"))

        result = await self._run(monkeypatch, fake)

        assert result is None  # pre-existing degradation unchanged
        providers = _providers()
        assert providers["akshare-cn"]["fail"] == 1
        assert providers["tencent-cn-hist"]["fail"] == 1


class TestFetchHistoricalWiring:
    @pytest.mark.asyncio
    async def test_em_dead_tencent_catches_records_the_pair(self, monkeypatch) -> None:
        fake = _RecorderAk(em_error=ConnectionError("TCP dropped"), tx_frame=_tx_frame())
        _install_ak(monkeypatch, fake)

        result = await fetcher_mod.fetch_historical("600519", "3y")

        assert result["dates"] == list(_DATES)  # data chain unchanged
        providers = _providers()
        assert providers["akshare-cn-hist"]["fail"] == 1
        assert providers["tencent-cn-hist"]["ok"] == 1

    @pytest.mark.asyncio
    async def test_healthy_em_records_ok_and_never_tencent(self, monkeypatch) -> None:
        fake = _RecorderAk(em_frame=_em_frame(), tx_error=RuntimeError("must not run"))
        _install_ak(monkeypatch, fake)

        result = await fetcher_mod.fetch_historical("600519", "3y")

        assert result["dates"] == list(_DATES)
        providers = _providers()
        assert providers["akshare-cn-hist"]["ok"] == 1
        assert "tencent-cn-hist" not in providers


class TestFetchHistoricalChainWiring:
    """Every attempt layer of fetch_historical's US/HK fallback chain.

    The CN branch records were iteration 101; these tests pin the remaining
    seams: a provider that was never called (no key / earlier layer ok) is
    never recorded, and every layer that does run records exactly one
    outcome without touching the data path.
    """

    _FULL_DEATH_PROVIDERS = {
        "yfinance-hist",
        "finnhub-hist",
        "alphavantage-hist",
        "sina-us-hist",
        "yahoo-api-hist",
        "stooq-hist",
    }

    @staticmethod
    def _install_healthy_yf(monkeypatch: pytest.MonkeyPatch) -> None:
        class _Ticker:
            def __init__(self, symbol: str) -> None:
                pass

            def history(self, **kwargs: Any) -> pd.DataFrame:
                index = pd.to_datetime(list(_DATES))
                return pd.DataFrame(
                    {
                        "Open": [10.0, 11.0, 12.0],
                        "High": [10.5, 11.5, 12.5],
                        "Low": [9.5, 10.5, 11.5],
                        "Close": [10.2, 11.2, 12.2],
                        "Volume": [1_000, 1_100, 1_200],
                    },
                    index=index,
                )

        monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=_Ticker))

    @staticmethod
    def _kill_tail(monkeypatch: pytest.MonkeyPatch) -> None:
        """Sina answers nothing usable; Yahoo/Stooq HTTP is dead — every
        layer below akshare fails without touching the network."""

        async def _dead_sina(symbol: str, period: str = fetcher_mod.DEFAULT_HISTORY_PERIOD) -> None:
            return None

        def _dead_get(*args: Any, **kwargs: Any) -> Any:
            raise requests.RequestException("blocked")

        monkeypatch.setattr(fetcher_mod, "_sina_us_hist", _dead_sina)
        monkeypatch.setattr(fetcher_mod.requests, "get", _dead_get)

    @pytest.mark.asyncio
    async def test_healthy_yfinance_records_ok_and_stops_chain(self, monkeypatch) -> None:
        self._install_healthy_yf(monkeypatch)

        result = await fetcher_mod.fetch_historical("AAPL", "3mo")

        assert result["dates"] == list(_DATES)
        assert result["close"] == [10.2, 11.2, 12.2]
        providers = _providers()
        assert set(providers) == {"yfinance-hist"}
        assert providers["yfinance-hist"]["ok"] == 1

    @pytest.mark.asyncio
    async def test_full_chain_death_records_every_layer_fail(self, monkeypatch) -> None:
        _install_ak(monkeypatch, _RecorderAk())  # dead yfinance; akshare importable
        get_settings().finnhub_api_key = "test-key"
        get_settings().alpha_vantage_key = "test-key"

        async def _free_tier_no_candle(symbol: str, period: str) -> None:
            return None  # /stock/candle is paid-only; nothing usable comes back

        async def _thin_av(symbol: str, period: str) -> dict[str, Any]:
            # free-tier cap shape: dates present, far short of the 3y window
            return {
                "dates": list(_DATES),
                "open": [],
                "high": [],
                "low": [],
                "close": [],
                "volume": [],
            }

        monkeypatch.setattr(fetcher_mod, "_finnhub_historical", _free_tier_no_candle)
        monkeypatch.setattr(fetcher_mod, "_alphavantage_historical", _thin_av)
        self._kill_tail(monkeypatch)

        result = await fetcher_mod.fetch_historical("AAPL", "3y")

        assert result == {"error": "All providers failed for AAPL", "symbol": "AAPL"}
        providers = _providers()
        assert set(providers) == self._FULL_DEATH_PROVIDERS
        for name in self._FULL_DEATH_PROVIDERS:
            assert providers[name]["fail"] == 1, name
            assert providers[name]["ok"] == 0, name
        assert providers["yfinance-hist"]["last_error"] == "RuntimeError: Too Many Requests"
        assert providers["finnhub-hist"]["last_error"] == "no dates"
        assert (
            providers["alphavantage-hist"]["last_error"] == "coverage gate: 3 bars cannot cover 3y"
        )
        assert "RequestException" in providers["yahoo-api-hist"]["last_error"]
        assert "RequestException" in providers["stooq-hist"]["last_error"]

    @pytest.mark.asyncio
    async def test_missing_api_keys_leave_keyed_layers_unrecorded(self, monkeypatch) -> None:
        _install_ak(monkeypatch, _RecorderAk())  # keys stay None via the autouse fixture
        self._kill_tail(monkeypatch)

        result = await fetcher_mod.fetch_historical("AAPL", "3y")

        assert result["error"].startswith("All providers failed")
        providers = _providers()
        assert set(providers) == {"yfinance-hist", "sina-us-hist", "yahoo-api-hist", "stooq-hist"}

    @pytest.mark.asyncio
    async def test_sina_ok_stops_chain_before_yahoo_and_stooq(self, monkeypatch) -> None:
        _install_ak(monkeypatch, _RecorderAk())

        async def _live_sina(
            symbol: str, period: str = fetcher_mod.DEFAULT_HISTORY_PERIOD
        ) -> dict[str, Any]:
            return {
                "dates": list(_DATES),
                "open": [10.0, 11.0, 12.0],
                "high": [10.5, 11.5, 12.5],
                "low": [9.5, 10.5, 11.5],
                "close": [10.2, 11.2, 12.2],
                "volume": [1_000, 1_100, 1_200],
            }

        monkeypatch.setattr(fetcher_mod, "_sina_us_hist", _live_sina)
        monkeypatch.setattr(
            fetcher_mod.requests,
            "get",
            lambda *args, **kwargs: pytest.fail("yahoo/stooq must not be called"),
        )

        result = await fetcher_mod.fetch_historical("AAPL", "3y")

        assert result["dates"] == list(_DATES)
        providers = _providers()
        assert set(providers) == {"yfinance-hist", "sina-us-hist"}
        assert providers["sina-us-hist"]["ok"] == 1

    @pytest.mark.asyncio
    async def test_hk_tencent_fail_akshare_hk_catches(self, monkeypatch) -> None:
        module = types.ModuleType("akshare")
        module.stock_hk_hist = lambda **kwargs: _em_frame()  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "akshare", module)
        monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=_DeadYf.Ticker))

        async def _tencent_dead(symbol: str) -> None:
            raise ConnectionError("HK quote drop")

        monkeypatch.setattr(fetcher_mod, "_tencent_hk_fetch", _tencent_dead)
        monkeypatch.setattr(fetcher_mod, "_eastmoney_hk_klines", lambda *args: [])

        result = await fetcher_mod.fetch_historical("0700.HK", "3y")

        assert result["dates"] == list(_DATES)
        providers = _providers()
        assert set(providers) == {"yfinance-hist", "tencent-hk-hist", "akshare-hk-hist"}
        assert providers["tencent-hk-hist"]["fail"] == 1
        assert "ConnectionError" in providers["tencent-hk-hist"]["last_error"]
        assert providers["akshare-hk-hist"]["ok"] == 1
        # eastmoney answered with no klines (and no exception): per the HK
        # seam's ok/exception wiring the no-klines fall-through records nothing.
        assert "eastmoney-hk-hist" not in providers


class TestFetchStockDataLoopWiring:
    """Every provider, every attempt — outcome tracking, not success stories."""

    @staticmethod
    def _priced(provider_name: str):
        async def _fetch(symbol: str) -> dict[str, Any]:
            return {
                "market_data": {"symbol": symbol, "current_price": 123.0},
                "financial_data": {"metrics": {}},
                "news_data": [],
                "provider": provider_name,
            }

        return _fetch

    @pytest.mark.asyncio
    async def test_chain_records_every_provider_outcome(self, monkeypatch) -> None:
        async def _no_price(symbol: str) -> dict[str, Any]:
            return {"market_data": {}, "financial_data": {"metrics": {}}, "news_data": []}

        async def _explodes(symbol: str) -> dict[str, Any]:
            raise ValueError("api key expired")

        monkeypatch.setattr(fetcher_mod, "_yfinance_fetch", _no_price)
        monkeypatch.setattr(fetcher_mod, "_alphavantage_fetch", _explodes)
        monkeypatch.setattr(fetcher_mod, "_finnhub_fetch", self._priced("finnhub"))
        monkeypatch.setattr(
            fetcher_mod,
            "_akshare_fetch",
            self._priced("akshare") if False else _no_price,  # never reached below finnhub's ok
        )

        result = await fetcher_mod.fetch_stock_data("AAPL")

        assert result is not None and result["market_data"]["current_price"] == 123.0
        providers = _providers()
        assert providers["yfinance"]["fail"] == 1
        assert providers["yfinance"]["last_error"] == "no price"
        assert providers["alphavantage"]["fail"] == 1
        assert "ValueError" in providers["alphavantage"]["last_error"]
        assert providers["finnhub"]["ok"] == 1
        # The chain stopped at finnhub's ok — later providers were never
        # called, so they must not be recorded.
        assert set(providers) == {"yfinance", "alphavantage", "finnhub"}

    @pytest.mark.asyncio
    async def test_first_provider_ok_records_only_that_provider(self, monkeypatch) -> None:
        monkeypatch.setattr(fetcher_mod, "_yfinance_fetch", self._priced("yfinance"))

        result = await fetcher_mod.fetch_stock_data("AAPL")

        assert result is not None
        assert set(_providers()) == {"yfinance"}
        assert _providers()["yfinance"]["ok"] == 1


def _spot_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "代码": "600519",
                "名称": "贵州茅台",
                "最新价": 1650.0,
                "涨跌额": 19.5,
                "涨跌幅": 1.2,
                "成交量": 25_000,
                "成交额": 4.1e9,
                "振幅": 2.1,
                "最高": 1660.0,
                "最低": 1635.0,
                "今开": 1640.0,
                "昨收": 1630.5,
            }
        ]
    )


class TestSpotTableWiring:
    async def _run(self, monkeypatch: pytest.MonkeyPatch, ak: Any, tx_result: Any) -> Any:
        monkeypatch.setattr(data_agent_mod, "tencent_cn_spot_table", lambda syms: tx_result)
        agent = AkShareDataAgent("akshare_data")
        agent.llm = None
        return await agent._fetch_akshare_spot_table(ak, ["600519"])

    @pytest.mark.asyncio
    async def test_em_dead_tencent_catches_records_the_pair(self, monkeypatch) -> None:
        def _em_dead():
            raise ConnectionError("Remote end closed connection without response")

        ak = types.SimpleNamespace(stock_zh_a_spot_em=_em_dead)

        df = await self._run(monkeypatch, ak, _spot_frame())

        assert df is not None and not df.empty
        providers = _providers()
        assert providers["em-spot-table"]["fail"] == 1
        assert "ConnectionError" in providers["em-spot-table"]["last_error"]
        assert providers["tencent-spot"]["ok"] == 1

    @pytest.mark.asyncio
    async def test_healthy_em_records_ok_and_never_tencent(self, monkeypatch) -> None:
        """EM healthy → the fallback is not even attempted → not recorded."""
        # The bomb must be deferred (lambda) — passing pytest.fail(...) as a
        # plain argument would raise during argument evaluation, before the
        # agent ever runs. Same pattern as TestBenchmarkHistoryWiring.
        monkeypatch.setattr(
            data_agent_mod,
            "tencent_cn_spot_table",
            lambda syms: pytest.fail("tencent must not be called"),
        )
        ak = types.SimpleNamespace(stock_zh_a_spot_em=lambda: _spot_frame())

        agent = AkShareDataAgent("akshare_data")
        agent.llm = None
        df = await agent._fetch_akshare_spot_table(ak, ["600519"])

        assert df is not None and not df.empty
        providers = _providers()
        assert providers["em-spot-table"]["ok"] == 1
        assert "tencent-spot" not in providers

    @pytest.mark.asyncio
    async def test_both_dead_records_both_fail(self, monkeypatch) -> None:
        def _em_dead():
            raise ConnectionError("EM drop")

        ak = types.SimpleNamespace(stock_zh_a_spot_em=_em_dead)

        df = await self._run(monkeypatch, ak, None)

        assert df is None  # pre-existing degradation unchanged
        providers = _providers()
        assert providers["em-spot-table"]["fail"] == 1
        assert providers["tencent-spot"]["fail"] == 1


class TestFinnhubNewsWiring:
    """fetch_us_news records its outcome (iteration 212/213 gap: the US news
    fallback was the one chain member invisible to provider-health — its
    exceptions are swallowed inside the fetcher, so only the fetcher itself
    can distinguish key-absent no-op from a called-and-dark feed)."""

    @pytest.mark.asyncio
    async def test_no_key_records_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No FINNHUB_API_KEY is a config-off no-op — never a recorded fail
        (same semantics the keyed historical layers already pin)."""
        await fetch_us_news("AAPL")
        assert "finnhub-news" not in _providers()

    @pytest.mark.asyncio
    async def test_articles_record_ok_with_count(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = get_settings()
        monkeypatch.setattr(settings, "finnhub_api_key", "test-key")
        items = [
            {"headline": f"Apple story {i}", "url": f"https://x/{i}", "datetime": 1, "source": "R"}
            for i in range(2)
        ]
        monkeypatch.setattr(fetcher_finnhub_mod, "_finnhub_get", lambda path, params: items)

        articles = await fetch_us_news("AAPL")

        assert len(articles) == 2
        entry = _providers()["finnhub-news"]
        assert entry["ok"] == 1 and entry["fail"] == 0
        assert entry["last_ok_at"] is not None and entry["last_error"] is None

    @pytest.mark.asyncio
    async def test_exception_records_fail_with_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = get_settings()
        monkeypatch.setattr(settings, "finnhub_api_key", "test-key")

        def _dark(path: str, params: dict) -> list:
            raise ConnectionError("feed dark")

        monkeypatch.setattr(fetcher_finnhub_mod, "_finnhub_get", _dark)

        articles = await fetch_us_news("AAPL")

        assert articles == []  # caller contract unchanged (empty feed, no raise)
        entry = _providers()["finnhub-news"]
        assert entry["fail"] == 1 and entry["ok"] == 0
        assert "ConnectionError" in entry["last_error"]

    @pytest.mark.asyncio
    async def test_empty_feed_records_fail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Key set + feed answered nothing mirrors em-news-cn's honest
        "feed returned nothing" fail — presence of the record is the wiring
        proof, the outcome is the feed's honesty."""
        settings = get_settings()
        monkeypatch.setattr(settings, "finnhub_api_key", "test-key")
        monkeypatch.setattr(fetcher_finnhub_mod, "_finnhub_get", lambda path, params: None)

        articles = await fetch_us_news("AAPL")

        assert articles == []
        entry = _providers()["finnhub-news"]
        assert entry["fail"] == 1
        assert "nothing" in entry["last_error"]
