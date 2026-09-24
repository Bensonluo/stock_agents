"""Benchmark plumbing for beta/alpha/R² regression.

The risk engine has supported benchmark regression since the V2
consolidation, but the data layer never fetched one — beta was permanently
insufficient_data in production runs. These tests pin the new plumbing:
per-market index attach (once per run, not per symbol), failure degradation,
and the AkShare state merge that must not drop the benchmark block.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock

import pytest


def _load_data_agent() -> ModuleType:
    """Load data_agent with stubbed base/state modules (package-cycle guard)."""
    base_module = ModuleType("app.agents.base")
    base_module.BaseAgent = type("BaseAgent", (), {})
    state_module = ModuleType("app.orchestration.state")
    state_module.AgentState = dict
    replaced = {
        name: sys.modules.get(name) for name in ("app.agents.base", "app.orchestration.state")
    }
    sys.modules.update({"app.agents.base": base_module, "app.orchestration.state": state_module})
    try:
        path = Path(__file__).parents[3] / "app" / "agents" / "data_agent.py"
        spec = importlib.util.spec_from_file_location("data_agent_benchmark", path)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        for name, original in replaced.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


@pytest.fixture
def data_agent_module():
    return _load_data_agent()


def _market(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "current_price": 10.0,
        "historical_data": {"dates": ["2026-01-02", "2026-01-03"], "close": [10.0, 10.5]},
    }


class TestBenchmarkTickerSelection:
    def test_six_digit_symbols_map_to_sse_composite(self):
        from app.tools.data.fetcher import benchmark_ticker_for

        assert benchmark_ticker_for("600000") == "000001.SS"

    def test_everything_else_maps_to_sp500(self):
        from app.tools.data.fetcher import benchmark_ticker_for

        assert benchmark_ticker_for("AAPL") == "^GSPC"
        assert benchmark_ticker_for("0700.HK") == "^GSPC"


class TestBenchmarkAttach:
    @staticmethod
    def _patch_per_symbol_fetches(data_agent_module, monkeypatch, market) -> None:
        monkeypatch.setattr(data_agent_module, "_sync_fetch_market_data", market)
        monkeypatch.setattr(
            data_agent_module.DataCollectionAgent,
            "_fetch_financial_data",
            AsyncMock(return_value={}),
        )
        monkeypatch.setattr(
            data_agent_module.DataCollectionAgent,
            "_fetch_news",
            AsyncMock(return_value=[]),
        )

    @pytest.mark.asyncio
    async def test_one_benchmark_per_market_attached_to_symbols(
        self, data_agent_module, monkeypatch
    ) -> None:
        agent = data_agent_module.DataCollectionAgent()
        self._patch_per_symbol_fetches(
            data_agent_module, monkeypatch, lambda yahoo, sym, conv: _market(sym)
        )
        calls: list[str] = []

        async def fake_benchmark(ticker):
            calls.append(ticker)
            return {"symbol": ticker, "dates": ["2026-01-02"], "close": [4800.0]}

        monkeypatch.setattr(data_agent_module, "fetch_benchmark_history", fake_benchmark)

        result = await agent.execute({"symbols": ["AAPL", "MSFT", "600000"]})

        # Exactly one fetch per represented market — never per symbol.
        assert sorted(calls) == ["000001.SS", "^GSPC"]
        assert result["market_data"]["AAPL"]["benchmark_historical_data"]["symbol"] == "^GSPC"
        assert result["market_data"]["MSFT"]["benchmark_historical_data"]["symbol"] == "^GSPC"
        assert result["market_data"]["600000"]["benchmark_historical_data"]["symbol"] == "000001.SS"

    @pytest.mark.asyncio
    async def test_benchmark_failure_leaves_symbols_intact_without_the_key(
        self, data_agent_module, monkeypatch
    ) -> None:
        agent = data_agent_module.DataCollectionAgent()
        self._patch_per_symbol_fetches(
            data_agent_module, monkeypatch, lambda yahoo, sym, conv: _market(sym)
        )

        async def failing_benchmark(ticker):
            # What the shared fetcher returns when the index fetch fails.
            return None

        monkeypatch.setattr(data_agent_module, "fetch_benchmark_history", failing_benchmark)

        result = await agent.execute({"symbols": ["AAPL"]})

        assert "benchmark_historical_data" not in result["market_data"]["AAPL"]
        assert result["market_data"]["AAPL"]["current_price"] == 10.0

    @pytest.mark.asyncio
    async def test_empty_market_data_gets_no_benchmark(
        self, data_agent_module, monkeypatch
    ) -> None:
        agent = data_agent_module.DataCollectionAgent()
        self._patch_per_symbol_fetches(data_agent_module, monkeypatch, lambda yahoo, sym, conv: {})

        async def canned_benchmark(ticker):
            return {"symbol": ticker, "dates": ["2026-01-02"], "close": [4800.0]}

        monkeypatch.setattr(data_agent_module, "fetch_benchmark_history", canned_benchmark)

        result = await agent.execute({"symbols": ["AAPL"]})

        assert result["market_data"]["AAPL"] == {}


class TestAkShareMergePreservesBenchmark:
    def test_merge_overrides_akshare_keys_but_keeps_yfinance_only_keys(self) -> None:
        from app.orchestration.orchestrator import _merge_symbol_maps

        bench = {"symbol": "000001.SS", "dates": ["2026-01-02"], "close": [3000.0]}
        existing = {
            "600000": {
                "historical_data": {"dates": ["yf"], "close": [1.0]},
                "current_price": 7.5,
                "benchmark_historical_data": bench,
            }
        }
        incoming = {
            "600000": {
                "historical_data": {"dates": ["ak"], "close": [2.0]},
                "as_of": "2026-09-23",
            },
            "600036": {"current_price": 40.0},
        }

        merged = _merge_symbol_maps(existing, incoming)

        # AkShare's data wins for the keys it sets…
        assert merged["600000"]["historical_data"]["close"] == [2.0]
        assert merged["600000"]["as_of"] == "2026-09-23"
        # …but the benchmark block and yfinance-only keys survive the merge.
        assert merged["600000"]["benchmark_historical_data"] is bench
        assert merged["600000"]["current_price"] == 7.5
        assert merged["600036"] == {"current_price": 40.0}

    def test_non_dict_values_replace(self) -> None:
        from app.orchestration.orchestrator import _merge_symbol_maps

        assert _merge_symbol_maps({"news_data": ["old"]}, {"news_data": ["new"]}) == {
            "news_data": ["new"]
        }
        assert _merge_symbol_maps({}, {"news_data": ["fresh"]}) == {"news_data": ["fresh"]}


class TestFetcherBenchmarkCache:
    """The shared fetcher caches benchmarks so ReAct's per-symbol tool calls
    download each index once per 30-min window, not once per symbol."""

    def setup_method(self):
        from app.tools.data import fetcher

        self.fetcher = fetcher
        fetcher._cache.clear()

    @pytest.mark.asyncio
    async def test_second_call_is_served_from_cache(self, monkeypatch) -> None:
        calls: list[str] = []

        def fake_sync(ticker):
            calls.append(ticker)
            return {"symbol": ticker, "dates": ["2026-01-02"], "close": [4800.0]}

        monkeypatch.setattr(self.fetcher, "_sync_fetch_benchmark_history", fake_sync)

        first = await self.fetcher.fetch_benchmark_history("^GSPC")
        second = await self.fetcher.fetch_benchmark_history("^GSPC")

        assert calls == ["^GSPC"]  # one sync fetch, second call cached
        assert first is second

    @pytest.mark.asyncio
    async def test_failed_fetch_returns_none_and_is_retried(self, monkeypatch) -> None:
        calls: list[str] = []

        def failing_sync(ticker):
            calls.append(ticker)
            raise RuntimeError("index feed down")

        monkeypatch.setattr(self.fetcher, "_sync_fetch_benchmark_history", failing_sync)

        assert await self.fetcher.fetch_benchmark_history("^GSPC") is None
        assert await self.fetcher.fetch_benchmark_history("^GSPC") is None
        assert len(calls) == 2  # failures are not cached as None


class TestCnIndustryBenchmark:
    """A-shares get the East Money industry-board index as their sector
    benchmark — SPDR ETFs have no vocabulary for Chinese sector names."""

    def setup_method(self):
        from app.tools.data import fetcher

        self.fetcher = fetcher
        fetcher._cache.clear()

    @staticmethod
    def _info_df(industry: str | None):
        import pandas as pd

        items = [("股票代码", "600000"), ("总市值", "3.0e11")]
        if industry is not None:
            items.append(("行业", industry))
        return pd.DataFrame(items, columns=["item", "value"])

    @staticmethod
    def _board_df():
        import pandas as pd

        return pd.DataFrame(
            {
                "日期": ["2026-01-02", "2026-01-03"],
                "开盘": [10.0, 10.2],
                "收盘": [10.0, 10.5],
                "最高": [10.6, 10.7],
                "最低": [9.9, 10.1],
                "成交量": [1000, 1100],
            }
        )

    def _install_fake_akshare(self, monkeypatch, info_df, board_df, calls):
        import sys
        from types import ModuleType

        fake = ModuleType("akshare")

        def stock_individual_info_em(symbol, timeout=None):
            calls.append(("info", symbol))
            return info_df

        def stock_board_industry_hist_em(symbol, start_date, end_date, period, adjust):
            calls.append(("board", symbol))
            return board_df

        fake.stock_individual_info_em = stock_individual_info_em
        fake.stock_board_industry_hist_em = stock_board_industry_hist_em
        monkeypatch.setitem(sys.modules, "akshare", fake)

    def test_sync_name_extracts_the_industry_row(self, monkeypatch) -> None:
        calls: list = []
        self._install_fake_akshare(monkeypatch, self._info_df("银行"), self._board_df(), calls)

        assert self.fetcher._sync_cn_industry_name("600000") == "银行"
        # Missing 行业 row degrades to None, never an exception.
        self._install_fake_akshare(monkeypatch, self._info_df(None), self._board_df(), calls)
        assert self.fetcher._sync_cn_industry_name("600000") is None

    def test_sync_history_maps_dates_and_closes(self, monkeypatch) -> None:
        calls: list = []
        self._install_fake_akshare(monkeypatch, self._info_df("银行"), self._board_df(), calls)

        bench = self.fetcher._sync_cn_industry_history("银行")

        assert bench == {
            "symbol": "银行",
            "dates": ["2026-01-02", "2026-01-03"],
            "close": [10.0, 10.5],
        }

    @pytest.mark.asyncio
    async def test_same_industry_symbols_share_one_board_fetch(self, monkeypatch) -> None:
        calls: list = []
        self._install_fake_akshare(monkeypatch, self._info_df("银行"), self._board_df(), calls)

        first = await self.fetcher.fetch_cn_sector_benchmark("600000")
        second = await self.fetcher.fetch_cn_sector_benchmark("600036")

        # Per-symbol industry lookups (two), one shared board history.
        assert [kind for kind, _ in calls] == ["info", "board", "info"]
        assert first is second
        assert first["symbol"] == "银行"

    @pytest.mark.asyncio
    async def test_board_failure_returns_none_and_is_retried(self, monkeypatch) -> None:
        import sys
        from types import ModuleType

        fake = ModuleType("akshare")

        def stock_individual_info_em(symbol, timeout=None):
            return self._info_df("银行")

        def stock_board_industry_hist_em(symbol, start_date, end_date, period, adjust):
            raise RuntimeError("board feed down")

        fake.stock_individual_info_em = stock_individual_info_em
        fake.stock_board_industry_hist_em = stock_board_industry_hist_em
        monkeypatch.setitem(sys.modules, "akshare", fake)

        assert await self.fetcher.fetch_cn_sector_benchmark("600000") is None
        # The industry name is cached; the failed board fetch is retried
        # (only the name call is skipped on the second attempt).

    @pytest.mark.asyncio
    async def test_cn_symbol_gets_industry_benchmark_attached(
        self, data_agent_module, monkeypatch
    ) -> None:
        agent = data_agent_module.DataCollectionAgent()
        TestBenchmarkAttach._patch_per_symbol_fetches(
            data_agent_module, monkeypatch, lambda yahoo, sym, conv: _market(sym)
        )

        async def canned_benchmark(ticker):
            return {"symbol": ticker, "dates": ["2026-01-02"], "close": [4800.0]}

        async def canned_cn(symbol):
            return {"symbol": "银行", "dates": ["2026-01-02"], "close": [2400.0]}

        monkeypatch.setattr(data_agent_module, "fetch_benchmark_history", canned_benchmark)
        monkeypatch.setattr(data_agent_module, "fetch_cn_sector_benchmark", canned_cn)

        result = await agent.execute({"symbols": ["AAPL", "600000"]})

        us_block = result["market_data"]["AAPL"]
        cn_block = result["market_data"]["600000"]
        assert cn_block["sector_benchmark_historical_data"]["symbol"] == "银行"
        # US symbols keep the SPDR path — no industry key fabricated for them.
        assert "sector_benchmark_historical_data" not in us_block

    @pytest.mark.asyncio
    async def test_cn_benchmark_failure_leaves_key_absent(
        self, data_agent_module, monkeypatch
    ) -> None:
        agent = data_agent_module.DataCollectionAgent()
        TestBenchmarkAttach._patch_per_symbol_fetches(
            data_agent_module, monkeypatch, lambda yahoo, sym, conv: _market(sym)
        )

        async def canned_benchmark(ticker):
            return {"symbol": ticker, "dates": ["2026-01-02"], "close": [4800.0]}

        async def failing_cn(symbol):
            return None

        monkeypatch.setattr(data_agent_module, "fetch_benchmark_history", canned_benchmark)
        monkeypatch.setattr(data_agent_module, "fetch_cn_sector_benchmark", failing_cn)

        result = await agent.execute({"symbols": ["600000"]})

        cn_block = result["market_data"]["600000"]
        assert "sector_benchmark_historical_data" not in cn_block
        assert cn_block["benchmark_historical_data"]["symbol"] == "000001.SS"

    @pytest.mark.asyncio
    async def test_react_attach_benchmark_covers_cn_symbols(self, monkeypatch) -> None:
        from app.tools.analysis import auto_tools

        async def canned_benchmark(ticker):
            return {"symbol": ticker, "dates": ["2026-01-02"], "close": [4800.0]}

        async def canned_cn(symbol):
            return {"symbol": "银行", "dates": ["2026-01-02"], "close": [2400.0]}

        monkeypatch.setattr(auto_tools, "fetch_benchmark_history", canned_benchmark)
        monkeypatch.setattr(auto_tools, "fetch_cn_sector_benchmark", canned_cn)

        market = await auto_tools._attach_benchmark({"symbol": "600000"}, "600000")

        assert market["benchmark_historical_data"]["symbol"] == "000001.SS"
        assert market["sector_benchmark_historical_data"]["symbol"] == "银行"
