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
        fallback_payload = {
            "market_data": {
                "TEST": {
                    "current_price": 123.45,
                    "historical_data": {"dates": ["2024-01-02"], "close": [100.0]},
                }
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
