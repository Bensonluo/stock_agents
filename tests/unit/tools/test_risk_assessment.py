"""Specification tests for the risk assessment tool."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from app.tools.risk.assessment import assess_risk


def _history(returns: np.ndarray) -> dict[str, list]:
    prices = [100.0]
    for value in returns:
        prices.append(prices[-1] * (1 + float(value)))
    dates = [(date(2024, 1, 1) + timedelta(days=index)).isoformat() for index in range(len(prices))]
    return {"dates": dates, "close": prices}


def test_tool_uses_aligned_benchmark_prices_for_beta() -> None:
    benchmark_returns = np.array(
        [(-1 if index % 4 == 0 else 1) * (0.002 + index * 0.0005) for index in range(24)]
    )

    result = assess_risk.invoke(
        {
            "market_data": {
                "TEST": {
                    "symbol": "TEST",
                    "historical_data": _history(benchmark_returns * 1.6),
                    "benchmark_historical_data": _history(benchmark_returns),
                }
            }
        }
    )["TEST"]

    assert result["metrics"]["beta"] == pytest.approx(1.6)
    assert result["metrics"]["beta_status"] == "available"
    assert result["risk_score_status"] == "complete"


def test_tool_does_not_fabricate_beta_or_position_when_benchmark_is_missing() -> None:
    result = assess_risk.invoke(
        {
            "market_data": {
                "TEST": {
                    "symbol": "TEST",
                    "historical_data": _history(np.linspace(-0.02, 0.025, 24)),
                }
            }
        }
    )["TEST"]

    assert result["metrics"]["beta"] is None
    assert result["metrics"]["beta_status"] == "insufficient_data"
    assert result["risk_score_status"] == "partial"
    assert result["position_recommendation"]["max_position_size"] is None


def test_tool_does_not_return_default_score_for_insufficient_prices() -> None:
    result = assess_risk.invoke(
        {
            "market_data": {
                "TEST": {
                    "symbol": "TEST",
                    "historical_data": {"dates": ["2024-01-01"], "close": [100.0]},
                }
            }
        }
    )["TEST"]

    assert result["risk_score"] is None
    assert result["risk_level"] == "insufficient_data"
    assert result["position_recommendation"]["max_position_size"] is None
