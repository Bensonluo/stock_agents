"""Sector-relative risk annotation: beta against your own industry ETF.

The market-benchmark regression (S&P 500 / SSE Composite) answers "how
risky vs everything"; it cannot see sector concentration — a quiet-looking
bank and a quiet-looking utility are not the same risk. This layer
regresses each US symbol against its SPDR sector ETF as an ANNOTATION
block beside the score (same contract as liquidity): the risk score and
position sizing never read it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock

import pytest

from app.tools.data.fetcher import sector_benchmark_ticker
from app.tools.risk.assessment import assess_symbol


def _bars(closes: list[float]) -> dict:
    dates = [f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(len(closes))]
    return {"dates": dates, "close": list(closes)}


def _correlated_pair(n: int = 25, multiple: float = 2.0) -> tuple[list[float], list[float]]:
    """Stock closes and a benchmark whose daily returns are the stock's
    returns divided by ``multiple`` — regressing stock on benchmark
    yields beta == multiple (the stock moves that many times the bench)."""
    stock_returns = [0.01, -0.004, 0.008, 0.012, -0.006] * (n // 5)
    stock, bench, ps, pb = [], [], 100.0, 200.0
    for r in stock_returns:
        stock.append(ps)
        bench.append(pb)
        ps *= 1 + r
        pb *= 1 + r / multiple
    return stock, bench


class TestSectorTickerMapping:
    def test_yfinance_sectors_map_to_spdr_etfs(self) -> None:
        assert sector_benchmark_ticker("Technology") == "XLK"
        assert sector_benchmark_ticker("Financial Services") == "XLF"
        assert sector_benchmark_ticker("Energy") == "XLE"

    def test_unknown_or_missing_sector_maps_to_none(self) -> None:
        assert sector_benchmark_ticker(None) is None
        assert sector_benchmark_ticker("") is None
        assert sector_benchmark_ticker("Whaling") is None

    def test_surrounding_whitespace_is_tolerated(self) -> None:
        assert sector_benchmark_ticker(" Technology ") == "XLK"


class TestSectorRelativeBlock:
    def test_available_block_reports_sector_regression(self) -> None:
        stock, bench = _correlated_pair(multiple=2.0)

        result = assess_symbol(
            "TEST",
            {
                "symbol": "TEST",
                "sector": "Technology",
                "historical_data": _bars(stock),
                "sector_benchmark_historical_data": {"symbol": "XLK", **_bars(bench)},
            },
        )

        block = result["sector_relative"]
        assert block["status"] == "available"
        assert block["sector"] == "Technology"
        assert block["benchmark_ticker"] == "XLK"
        assert block["beta_sector"] == pytest.approx(2.0, abs=1e-6)
        assert block["r_squared_sector"] == pytest.approx(1.0, abs=1e-6)
        assert block["correlation_sector"] == pytest.approx(1.0, abs=1e-6)

    def test_absent_sector_history_degrades_to_insufficient(self) -> None:
        stock, _ = _correlated_pair()

        result = assess_symbol(
            "TEST",
            {
                "symbol": "TEST",
                "sector": "Technology",
                "historical_data": _bars(stock),
            },
        )

        block = result["sector_relative"]
        assert block["status"] == "insufficient_data"
        assert block["sector"] == "Technology"
        assert "beta_sector" not in block

    def test_disjoint_dates_degrade_to_insufficient(self) -> None:
        stock, bench = _correlated_pair()
        disjoint = {
            "dates": [f"2019-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(len(bench))],
            "close": list(bench),
        }

        result = assess_symbol(
            "TEST",
            {
                "symbol": "TEST",
                "sector": "Technology",
                "historical_data": _bars(stock),
                "sector_benchmark_historical_data": {"symbol": "XLK", **disjoint},
            },
        )

        assert result["sector_relative"]["status"] == "insufficient_data"

    def test_sector_annotation_is_pure_risk_score_unchanged(self) -> None:
        stock, bench = _correlated_pair()
        base = {
            "symbol": "TEST",
            "sector": "Technology",
            "historical_data": _bars(stock),
        }

        with_sector = assess_symbol(
            "TEST", {**base, "sector_benchmark_historical_data": {"symbol": "XLK", **_bars(bench)}}
        )
        without = assess_symbol("TEST", dict(base))

        # Sector regression is reported beside the score, never folded in.
        assert with_sector["risk_score"] == without["risk_score"]
        assert with_sector["risk_level"] == without["risk_level"]
        assert with_sector["metrics"]["volatility"] == without["metrics"]["volatility"]


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
        spec = importlib.util.spec_from_file_location("data_agent_sector", path)
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


class TestSectorBenchmarkAttach:
    @staticmethod
    def _market(symbol: str, sector: str | None) -> dict:
        data = {
            "symbol": symbol,
            "current_price": 10.0,
            "historical_data": {"dates": ["2026-01-02", "2026-01-03"], "close": [10.0, 10.5]},
        }
        if sector:
            data["sector"] = sector
        return data

    @pytest.mark.asyncio
    async def test_one_sector_etf_per_mapped_sector(self, monkeypatch) -> None:
        module = _load_data_agent()
        agent = module.DataCollectionAgent()
        monkeypatch.setattr(
            module,
            "_sync_fetch_market_data",
            lambda yahoo, sym, conv: self._market(sym, "Technology" if sym != "600000" else None),
        )
        monkeypatch.setattr(
            module.DataCollectionAgent, "_fetch_financial_data", AsyncMock(return_value={})
        )
        monkeypatch.setattr(module.DataCollectionAgent, "_fetch_news", AsyncMock(return_value=[]))
        calls: list[str] = []

        async def fake_benchmark(ticker):
            calls.append(ticker)
            return {"symbol": ticker, "dates": ["2026-01-02"], "close": [100.0]}

        monkeypatch.setattr(module, "fetch_benchmark_history", fake_benchmark)

        result = await agent.execute({"symbols": ["AAPL", "MSFT", "600000"]})

        # Market index once per market + the sector ETF once, never per symbol.
        assert calls.count("XLK") == 1
        assert result["market_data"]["AAPL"]["sector_benchmark_historical_data"]["symbol"] == "XLK"
        assert result["market_data"]["MSFT"]["sector_benchmark_historical_data"]["symbol"] == "XLK"
        # CN spot rows carry no sector — no sector benchmark, market one intact.
        assert "sector_benchmark_historical_data" not in result["market_data"]["600000"]
        assert result["market_data"]["600000"]["benchmark_historical_data"]["symbol"] == "000001.SS"

    @pytest.mark.asyncio
    async def test_failed_sector_fetch_leaves_key_absent(self, monkeypatch) -> None:
        module = _load_data_agent()
        agent = module.DataCollectionAgent()
        monkeypatch.setattr(
            module,
            "_sync_fetch_market_data",
            lambda yahoo, sym, conv: self._market(sym, "Technology"),
        )
        monkeypatch.setattr(
            module.DataCollectionAgent, "_fetch_financial_data", AsyncMock(return_value={})
        )
        monkeypatch.setattr(module.DataCollectionAgent, "_fetch_news", AsyncMock(return_value=[]))

        async def half_failing(ticker):
            if ticker == "XLK":
                return None
            return {"symbol": ticker, "dates": ["2026-01-02"], "close": [100.0]}

        monkeypatch.setattr(module, "fetch_benchmark_history", half_failing)

        result = await agent.execute({"symbols": ["AAPL"]})

        assert "sector_benchmark_historical_data" not in result["market_data"]["AAPL"]
        assert result["market_data"]["AAPL"]["benchmark_historical_data"]["symbol"] == "^GSPC"
