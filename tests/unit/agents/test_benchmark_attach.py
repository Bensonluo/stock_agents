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
    def test_six_digit_symbols_map_to_sse_composite(self, data_agent_module):
        assert data_agent_module._benchmark_ticker_for("600000") == "000001.SS"

    def test_everything_else_maps_to_sp500(self, data_agent_module):
        assert data_agent_module._benchmark_ticker_for("AAPL") == "^GSPC"
        assert data_agent_module._benchmark_ticker_for("0700.HK") == "^GSPC"


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

        def fake_benchmark(ticker):
            calls.append(ticker)
            return {"symbol": ticker, "dates": ["2026-01-02"], "close": [4800.0]}

        monkeypatch.setattr(data_agent_module, "_sync_fetch_benchmark_history", fake_benchmark)

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

        def failing_benchmark(ticker):
            raise RuntimeError("index feed unavailable")

        monkeypatch.setattr(data_agent_module, "_sync_fetch_benchmark_history", failing_benchmark)

        result = await agent.execute({"symbols": ["AAPL"]})

        assert "benchmark_historical_data" not in result["market_data"]["AAPL"]
        assert result["market_data"]["AAPL"]["current_price"] == 10.0

    @pytest.mark.asyncio
    async def test_empty_market_data_gets_no_benchmark(
        self, data_agent_module, monkeypatch
    ) -> None:
        agent = data_agent_module.DataCollectionAgent()
        self._patch_per_symbol_fetches(data_agent_module, monkeypatch, lambda yahoo, sym, conv: {})
        monkeypatch.setattr(
            data_agent_module,
            "_sync_fetch_benchmark_history",
            lambda ticker: {"symbol": ticker, "dates": ["2026-01-02"], "close": [4800.0]},
        )

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
