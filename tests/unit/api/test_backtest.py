"""Unit tests for the backtest request contract."""

import pytest
from pydantic import ValidationError

from app.api.routes.backtest import BacktestRequest

BASE_REQUEST = {
    "symbol": "aapl",
    "strategy": "buy_and_hold",
    "start_date": "2024-01-01",
    "end_date": "2024-12-31",
}


@pytest.mark.parametrize(
    ("strategy", "overrides", "expected"),
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
def test_strategy_params_only_contains_selected_strategy_parameters(
    strategy: str,
    overrides: dict[str, int | float],
    expected: dict[str, int | float],
) -> None:
    request = BacktestRequest.model_validate({**BASE_REQUEST, "strategy": strategy, **overrides})

    assert request.symbol == "AAPL"
    assert request.strategy_params == expected


@pytest.mark.parametrize(
    ("strategy", "expected"),
    [
        ("sma_crossover", {"sma_short": 20, "sma_long": 50}),
        (
            "rsi_strategy",
            {"rsi_period": 14, "rsi_overbought": 70, "rsi_oversold": 30},
        ),
        (
            "macd_strategy",
            {"fast_period": 12, "slow_period": 26, "signal_period": 9},
        ),
        ("buy_and_hold", {}),
    ],
)
def test_strategy_params_supplies_strategy_defaults(
    strategy: str, expected: dict[str, int | float]
) -> None:
    request = BacktestRequest.model_validate({**BASE_REQUEST, "strategy": strategy})

    assert request.strategy_params == expected


@pytest.mark.parametrize(
    "updates",
    [
        {"strategy": "unknown"},
        {"start_date": "2024-02-30"},
        {"end_date": "2024-01-01"},
        {"strategy": "sma_crossover", "sma_short": 50, "sma_long": 50},
        {"strategy": "rsi_strategy", "rsi_oversold": 70, "rsi_overbought": 70},
        {"strategy": "macd_strategy", "fast_period": 26, "slow_period": 26},
        {"unexpected_parameter": 1},
    ],
)
def test_invalid_or_unknown_request_values_are_rejected(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        BacktestRequest.model_validate({**BASE_REQUEST, **updates})


@pytest.mark.parametrize(
    "payload",
    [
        {
            **BASE_REQUEST,
            "strategy": "sma_crossover",
            "sma_short": 5,
            "sma_long": 200,
        },
        {
            **BASE_REQUEST,
            "strategy": "rsi_strategy",
            "rsi_period": 5,
            "rsi_oversold": 0,
            "rsi_overbought": 100,
        },
        {
            **BASE_REQUEST,
            "strategy": "macd_strategy",
            "fast_period": 2,
            "slow_period": 200,
            "signal_period": 2,
        },
        {**BASE_REQUEST, "initial_cash": 1000, "commission": 0},
        {**BASE_REQUEST, "initial_cash": 1000, "commission": 0.1},
    ],
)
def test_documented_boundary_values_are_accepted(payload: dict[str, object]) -> None:
    BacktestRequest.model_validate(payload)
