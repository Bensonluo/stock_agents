"""Risk correctness specifications for the symbol-only analysis tool."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from app.tools.analysis import auto_tools


def _history(returns: np.ndarray) -> dict[str, list]:
    prices = [100.0]
    for value in returns:
        prices.append(prices[-1] * (1 + float(value)))
    dates = [(date(2024, 1, 1) + timedelta(days=index)).isoformat() for index in range(len(prices))]
    return {"dates": dates, "close": prices}


@pytest.mark.asyncio
async def test_symbol_only_tool_does_not_fabricate_beta_or_position(monkeypatch) -> None:
    async def fake_fetch(symbol: str) -> dict:
        return {
            "market_data": {
                symbol: {
                    "symbol": symbol,
                    "historical_data": _history(np.linspace(-0.02, 0.025, 24)),
                }
            },
            "financial_data": {},
            "news_data": [],
        }

    monkeypatch.setattr(auto_tools, "_fetch_and_split", fake_fetch)

    result = await auto_tools.assess_risk.ainvoke({"symbol": "TEST"})

    assert result["metrics"]["beta"] is None
    assert result["metrics"]["beta_status"] == "insufficient_data"
    assert result["risk_score_status"] == "partial"
    assert result["position_recommendation"]["max_position_size"] is None


@pytest.mark.asyncio
async def test_fetch_and_split_attaches_benchmark(monkeypatch) -> None:
    async def fake_snapshot(symbol: str) -> dict:
        return {
            "market_data": {
                symbol: {
                    "symbol": symbol,
                    "current_price": 10.0,
                    "historical_data": _history(np.linspace(-0.01, 0.01, 30)),
                }
            },
            "financial_data": {},
            "news_data": [],
        }

    async def fake_bench(ticker: str) -> dict:
        return {"symbol": ticker, "dates": ["2024-01-01"], "close": [4000.0]}

    monkeypatch.setattr(auto_tools, "fetch_stock_data", fake_snapshot)
    monkeypatch.setattr(auto_tools, "fetch_benchmark_history", fake_bench)

    data = await auto_tools._fetch_and_split("TEST")

    assert data["market_data"]["TEST"]["benchmark_historical_data"]["symbol"] == "^GSPC"


@pytest.mark.asyncio
async def test_tool_output_is_the_canonical_assess_symbol_block(monkeypatch) -> None:
    market = {
        "symbol": "TEST",
        "historical_data": _history(np.linspace(-0.02, 0.025, 60)),
        "benchmark_historical_data": _history(np.linspace(-0.01, 0.015, 60)),
    }

    async def fake_fetch(symbol: str) -> dict:
        return {"market_data": {symbol: market}, "financial_data": {}, "news_data": []}

    monkeypatch.setattr(auto_tools, "_fetch_and_split", fake_fetch)

    from app.tools.risk.assessment import assess_symbol

    result = await auto_tools.assess_risk.ainvoke({"symbol": "TEST"})

    # Bit-for-bit parity with the engine path the pipeline risk agent uses.
    assert result == assess_symbol("TEST", market)
    # The canonical block carries guarded VaR + CVaR + live beta — the old
    # inline copy lacked the >=20-return guard and CVaR entirely.
    assert result["metrics"]["cvar_95"] is not None
    assert result["metrics"]["beta"] is not None
    assert result["risk_score_status"] == "complete"
