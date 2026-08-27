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

