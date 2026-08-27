"""Unit tests for strategy construction and backtest execution."""

from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest

from app.services.backtest_service import BacktestService


def _market_data() -> pd.DataFrame:
    index = pd.date_range("2023-01-02", periods=180, freq="B")
    wave = np.sin(np.linspace(0, 12 * np.pi, len(index))) * 4
    close = 100 + np.linspace(0, 15, len(index)) + wave
    return pd.DataFrame(
        {
            "Open": close - 0.2,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.full(len(index), 1_000_000),
        },
        index=index,
    )


@pytest.mark.parametrize(
    ("strategy", "params"),
    [
        (
            "sma_crossover",
            {
                "sma_short": 10,
                "sma_long": 30,
                "rsi_period": 7,
                "fast_period": 5,
            },
        ),
        (
            "rsi_strategy",
            {
                "rsi_period": 10,
                "rsi_overbought": 75,
                "rsi_oversold": 25,
                "sma_short": 5,
                "signal_period": 4,
            },
        ),
        (
            "macd_strategy",
            {
                "fast_period": 8,
                "slow_period": 21,
                "signal_period": 5,
                "rsi_period": 9,
            },
        ),
        (
            "buy_and_hold",
            {"sma_short": 5, "rsi_period": 9, "fast_period": 8},
        ),
    ],
)
@pytest.mark.asyncio
async def test_each_strategy_runs_with_only_its_own_parameters(
    strategy: str, params: dict[str, int]
) -> None:
    service = BacktestService()
    service._fetch_data = AsyncMock(return_value=_market_data())

    result = await service.run_backtest(
        symbol="AAPL",
        strategy=strategy,
        start_date="2023-01-01",
        end_date="2024-01-01",
        strategy_params=params,
    )

    assert result["strategy"] == strategy
    assert result["final_value"] > 0
    assert isinstance(result["total_trades"], int)


def test_unknown_strategy_parameter_is_rejected() -> None:
    service = BacktestService()

    with pytest.raises(ValueError, match="Unknown strategy parameter: typo_period"):
        service._get_strategy_params("sma_crossover", {"typo_period": 10})


def test_unknown_strategy_is_rejected_before_parameters_are_processed() -> None:
    service = BacktestService()

    with pytest.raises(ValueError, match="Unknown strategy: mystery"):
        service._get_strategy_params("mystery", {})
