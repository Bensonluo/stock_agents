"""Tests for the pipeline's shared provider-chain fallback (data unification)."""

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
        spec = importlib.util.spec_from_file_location("data_agent_fallback", path)
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


class TestProviderFallback:
    @pytest.mark.asyncio
    async def test_empty_yfinance_result_falls_back_to_shared_chain(
        self, data_agent_module, monkeypatch
    ) -> None:
        agent = data_agent_module.DataCollectionAgent()
        # Canonical post-flatten shape: fetch_stock_data normalizes every
        # provider (keyed or flat) to this FLAT block — with "symbol" injected
        # as a string value — at its boundary. The previous keyed fake pinned
        # the pre-flatten provider contract and passed only because it mirrored
        # the broken keyed read below it.
        fallback_payload = {
            "market_data": {
                "symbol": "TEST",
                "current_price": 123.45,
                "historical_data": {"dates": ["2024-01-02"], "close": [100.0]},
            }
        }
        monkeypatch.setattr(
            data_agent_module, "fetch_stock_data", AsyncMock(return_value=fallback_payload)
        )
        monkeypatch.setattr(
            data_agent_module,
            "_sync_fetch_market_data",
            lambda *args, **kwargs: {},  # primary path returns nothing
        )

        result = await agent._fetch_market_data("TEST")

        assert result["symbol"] == "TEST"
        assert result["current_price"] == 123.45
        assert result["historical_data"]["close"] == [100.0]

    @pytest.mark.asyncio
    async def test_primary_result_short_circuits_the_chain(
        self, data_agent_module, monkeypatch
    ) -> None:
        agent = data_agent_module.DataCollectionAgent()
        fetch_mock = AsyncMock()
        monkeypatch.setattr(data_agent_module, "fetch_stock_data", fetch_mock)
        monkeypatch.setattr(
            data_agent_module,
            "_sync_fetch_market_data",
            lambda *args, **kwargs: {
                "symbol": "TEST",
                "historical_data": {"dates": ["2024-01-02"], "close": [1.0]},
            },
        )

        result = await agent._fetch_market_data("TEST")

        assert result["historical_data"]["close"] == [1.0]
        fetch_mock.assert_not_awaited()

    def test_history_window_constant_is_shared(self, data_agent_module) -> None:
        from app.tools.data.fetcher import DEFAULT_HISTORY_DAYS

        assert data_agent_module.DEFAULT_HISTORY_DAYS is DEFAULT_HISTORY_DAYS


class TestFinancialFallback:
    @pytest.mark.asyncio
    async def test_empty_yfinance_financials_fall_back_to_shared_chain(
        self, data_agent_module, monkeypatch
    ) -> None:
        agent = data_agent_module.DataCollectionAgent()
        # Same flat boundary contract as the market leg: financial_data IS
        # the block (metrics + metric_units), never symbol-keyed.
        fallback_payload = {
            "financial_data": {
                "metrics": {"pe_ratio": 28.4, "roe": 0.31},
                "metric_units": {"roe": "ratio"},
            }
        }
        monkeypatch.setattr(
            data_agent_module, "fetch_stock_data", AsyncMock(return_value=fallback_payload)
        )
        monkeypatch.setattr(
            data_agent_module,
            "_sync_fetch_financial_data",
            lambda *args, **kwargs: {},  # primary path returns nothing
        )

        result = await agent._fetch_financial_data("TEST")

        assert result["metrics"]["pe_ratio"] == 28.4
        assert result["metrics"]["roe"] == 0.31
        assert result["symbol"] == "TEST"  # injected, mirrors the market leg
        assert result["metric_units"] == {"roe": "ratio"}

    @pytest.mark.asyncio
    async def test_primary_financials_short_circuit_the_chain(
        self, data_agent_module, monkeypatch
    ) -> None:
        agent = data_agent_module.DataCollectionAgent()
        fetch_mock = AsyncMock()
        monkeypatch.setattr(data_agent_module, "fetch_stock_data", fetch_mock)
        monkeypatch.setattr(
            data_agent_module,
            "_sync_fetch_financial_data",
            lambda *args, **kwargs: {
                "symbol": "TEST",
                "metrics": {"pe_ratio": 12.0},
            },
        )

        result = await agent._fetch_financial_data("TEST")

        assert result["metrics"]["pe_ratio"] == 12.0
        fetch_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_metricless_chain_result_degrades_to_empty(
        self, data_agent_module, monkeypatch
    ) -> None:
        """A chain snapshot without metrics (e.g. a market-only provider)
        must not fabricate financial data — the pre-fallback degradation."""
        agent = data_agent_module.DataCollectionAgent()
        monkeypatch.setattr(
            data_agent_module,
            "fetch_stock_data",
            AsyncMock(return_value={"market_data": {"symbol": "TEST"}, "financial_data": {}}),
        )
        monkeypatch.setattr(
            data_agent_module,
            "_sync_fetch_financial_data",
            lambda *args, **kwargs: {},
        )

        result = await agent._fetch_financial_data("TEST")

        assert result == {}
