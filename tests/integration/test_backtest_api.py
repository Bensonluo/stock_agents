"""Integration tests for the backtest API request-to-service boundary."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.routes.backtest as backtest_route

RESULT = {
    "final_value": 11_000.0,
    "total_return": 1_000.0,
    "total_return_pct": 10.0,
    "annual_return": 10.0,
    "sharpe_ratio": 1.1,
    "max_drawdown": 5.0,
    "win_rate": 50.0,
    "total_trades": 2,
    "equity": [
        {"date": "2024-01-01", "value": 10_000.0},
        {"date": "2024-12-31", "value": 11_000.0},
    ],
}


@pytest.fixture
def backtest_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, AsyncMock]:
    service = AsyncMock()
    service.run_backtest.return_value = RESULT
    monkeypatch.setattr(backtest_route, "BacktestService", lambda: service)

    app = FastAPI()
    app.include_router(backtest_route.router, prefix="/api/backtest")
    return TestClient(app), service.run_backtest


@pytest.mark.parametrize(
    ("strategy", "parameters", "expected_params"),
    [
        (
            "sma_crossover",
            {"sma_short": 10, "sma_long": 40},
            {"sma_short": 10, "sma_long": 40},
        ),
        (
            "rsi_strategy",
            {"rsi_period": 9, "rsi_overbought": 75, "rsi_oversold": 25},
            {"rsi_period": 9, "rsi_overbought": 75, "rsi_oversold": 25},
        ),
        (
            "macd_strategy",
            {"fast_period": 8, "slow_period": 21, "signal_period": 5},
            {"fast_period": 8, "slow_period": 21, "signal_period": 5},
        ),
        ("buy_and_hold", {}, {}),
    ],
)
def test_run_endpoint_passes_only_selected_strategy_parameters(
    backtest_client: tuple[TestClient, AsyncMock],
    strategy: str,
    parameters: dict[str, int | float],
    expected_params: dict[str, int | float],
) -> None:
    client, run_backtest = backtest_client

    response = client.post(
        "/api/backtest/run",
        json={
            "symbol": "aapl",
            "strategy": strategy,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            **parameters,
        },
    )

    assert response.status_code == 200
    assert response.json()["symbol"] == "AAPL"
    assert run_backtest.await_args.kwargs["strategy_params"] == expected_params


def test_run_endpoint_rejects_unknown_fields_without_calling_service(
    backtest_client: tuple[TestClient, AsyncMock],
) -> None:
    client, run_backtest = backtest_client

    response = client.post(
        "/api/backtest/run",
        json={
            "symbol": "AAPL",
            "strategy": "buy_and_hold",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "mystery_period": 10,
        },
    )

    assert response.status_code == 422
    run_backtest.assert_not_awaited()
