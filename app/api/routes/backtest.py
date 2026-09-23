"""Backtesting endpoints."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.backtest_service import BacktestService
from app.utils.logging import get_logger
from app.utils.validators import validate_stock_symbol

logger = get_logger(__name__)

router = APIRouter()


# Request/Response Models
class BacktestRequest(BaseModel):
    """Request model for backtesting."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "symbol": "AAPL",
                "strategy": "sma_crossover",
                "start_date": "2023-01-01",
                "end_date": "2024-01-01",
                "initial_cash": 10000,
                "commission": 0.001,
                "sma_short": 20,
                "sma_long": 50,
            }
        },
    )

    symbol: str = Field(..., description="Stock symbol to backtest")
    strategy: Literal["sma_crossover", "rsi_strategy", "macd_strategy", "buy_and_hold"] = Field(
        ..., description="Strategy name"
    )
    start_date: str = Field(
        ..., description="Start date (YYYY-MM-DD)", pattern=r"^\d{4}-\d{2}-\d{2}$"
    )
    end_date: str = Field(..., description="End date (YYYY-MM-DD)", pattern=r"^\d{4}-\d{2}-\d{2}$")
    initial_cash: float = Field(default=10000.0, ge=1000, description="Initial cash amount")
    commission: float = Field(default=0.001, ge=0, le=0.1, description="Commission rate")

    # Strategy parameters
    sma_short: int = Field(default=20, ge=5, le=100)
    sma_long: int = Field(default=50, ge=10, le=200)
    rsi_period: int = Field(default=14, ge=5, le=50)
    rsi_overbought: float = Field(default=70, ge=50, le=100)
    rsi_oversold: float = Field(default=30, ge=0, le=50)
    fast_period: int = Field(default=12, ge=2, le=100)
    slow_period: int = Field(default=26, ge=3, le=200)
    signal_period: int = Field(default=9, ge=2, le=100)

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        """Validate stock symbol."""
        if not validate_stock_symbol(value):
            raise ValueError(f"Invalid stock symbol: {value}")
        return value.upper()

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_calendar_date(cls, value: str) -> str:
        """Reject strings that match the pattern but are not calendar dates."""
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("Date must be a valid calendar date in YYYY-MM-DD format") from exc
        return value

    @model_validator(mode="after")
    def validate_strategy_constraints(self) -> "BacktestRequest":
        """Validate relationships that depend on the selected strategy."""
        start = datetime.strptime(self.start_date, "%Y-%m-%d")
        end = datetime.strptime(self.end_date, "%Y-%m-%d")
        if end <= start:
            raise ValueError("End date must be after start date")

        if self.strategy == "sma_crossover" and self.sma_short >= self.sma_long:
            raise ValueError("sma_short must be less than sma_long")
        if self.strategy == "rsi_strategy" and self.rsi_oversold >= self.rsi_overbought:
            raise ValueError("rsi_oversold must be less than rsi_overbought")
        if self.strategy == "macd_strategy" and self.fast_period >= self.slow_period:
            raise ValueError("fast_period must be less than slow_period")
        return self

    @property
    def strategy_params(self) -> dict[str, int | float]:
        """Return only the parameters accepted by the selected strategy."""
        parameter_names = {
            "sma_crossover": ("sma_short", "sma_long"),
            "rsi_strategy": ("rsi_period", "rsi_overbought", "rsi_oversold"),
            "macd_strategy": ("fast_period", "slow_period", "signal_period"),
            "buy_and_hold": (),
        }
        return {name: getattr(self, name) for name in parameter_names[self.strategy]}


class BacktestResponse(BaseModel):
    """Response model for backtesting results."""

    symbol: str
    strategy: str
    period: dict[str, str]
    initial_cash: float
    final_value: float
    total_return: float
    total_return_pct: float
    annual_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    total_trades: int
    equity: list[dict[str, float | str]]
    execution_time: float


@router.post("/run")
async def run_backtest(request: BacktestRequest) -> BacktestResponse:
    """Run a backtest for the given strategy and symbol.

    Args:
        request: Backtest request

    Returns:
        Backtest results
    """
    from time import time

    logger.info(
        f"Running backtest for {request.symbol} with {request.strategy} strategy "
        f"from {request.start_date} to {request.end_date}"
    )

    start_time = time()

    try:
        backtest_service = BacktestService()

        # Run backtest
        result = await backtest_service.run_backtest(
            symbol=request.symbol,
            strategy=request.strategy,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_cash=request.initial_cash,
            commission=request.commission,
            strategy_params=request.strategy_params,
        )

        execution_time = time() - start_time

        logger.info(f"Backtest completed in {execution_time:.2f}s")

        return BacktestResponse(
            symbol=request.symbol,
            strategy=request.strategy,
            period={
                "start": request.start_date,
                "end": request.end_date,
            },
            initial_cash=request.initial_cash,
            final_value=result["final_value"],
            total_return=result["total_return"],
            total_return_pct=result["total_return_pct"],
            annual_return=result["annual_return"],
            sharpe_ratio=result["sharpe_ratio"],
            max_drawdown=result["max_drawdown"],
            win_rate=result["win_rate"],
            total_trades=result["total_trades"],
            equity=result["equity"],
            execution_time=execution_time,
        )

    except Exception as e:
        logger.error(f"Backtest failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/strategies")
async def list_strategies():
    """List available backtesting strategies.

    Returns:
        List of available strategies
    """
    return {
        "strategies": [
            {
                "name": "sma_crossover",
                "description": "Simple Moving Average Crossover",
                "parameters": {
                    "sma_short": "Short SMA period (default: 20)",
                    "sma_long": "Long SMA period (default: 50)",
                },
            },
            {
                "name": "rsi_strategy",
                "description": "RSI Overbought/Oversold",
                "parameters": {
                    "rsi_period": "RSI period (default: 14)",
                    "rsi_overbought": "Overbought threshold (default: 70)",
                    "rsi_oversold": "Oversold threshold (default: 30)",
                },
            },
            {
                "name": "macd_strategy",
                "description": "MACD Signal Line Crossover",
                "parameters": {
                    "fast_period": "Fast EMA period (default: 12)",
                    "slow_period": "Slow EMA period (default: 26)",
                    "signal_period": "Signal line period (default: 9)",
                },
            },
            {
                "name": "buy_and_hold",
                "description": "Buy and Hold Benchmark",
                "parameters": {},
            },
        ]
    }


@router.get("/results/{backtest_id}")
async def get_backtest_result(backtest_id: str):
    """Get a specific backtest result by ID.

    Args:
        backtest_id: Backtest result ID

    Returns:
        Backtest result details
    """
    # In a real implementation, this would fetch from a database
    raise HTTPException(status_code=501, detail="Not implemented - results are not persisted")


# ---------------------------------------------------------------------------
# V2 endpoints: deterministic engine, full costs, walk-forward, manifest
# ---------------------------------------------------------------------------


class V2BacktestRequest(BaseModel):
    """Request for the V2 deterministic backtest engine."""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(..., description="Stock symbol to backtest")
    strategy: Literal["sma_crossover", "rsi_strategy", "macd_strategy", "buy_and_hold"] = Field(
        ..., description="Strategy name"
    )
    start_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    initial_cash: float = Field(default=10000.0, ge=1000)
    market: Literal["us", "cn"] = Field(
        default="us",
        description="Cost preset: 'us' (commission+slippage) or 'cn' (+stamp tax, min fee)",
    )
    strategy_params: dict[str, float | int] = Field(
        default_factory=dict, description="Only the selected strategy's parameters"
    )
    benchmark_symbol: str | None = Field(
        default=None, description="Optional benchmark for the excess-return metric (e.g. '^GSPC')"
    )

    @field_validator("symbol")
    @classmethod
    def _validate_symbol(cls, value: str) -> str:
        if not validate_stock_symbol(value):
            raise ValueError(f"Invalid stock symbol: {value}")
        return value.upper()

    @field_validator("benchmark_symbol")
    @classmethod
    def _validate_benchmark(cls, value: str | None) -> str | None:
        # Benchmarks are indices/ETFs (^GSPC, 000300.SS), not stock symbols —
        # the strict stock validator rejects the caret forms.
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned or any(ch.isspace() for ch in cleaned):
            raise ValueError(f"Invalid benchmark symbol: {value}")
        return cleaned

    @model_validator(mode="after")
    def _dates_in_order(self) -> "V2BacktestRequest":
        start, end = datetime.strptime(self.start_date, "%Y-%m-%d"), datetime.strptime(
            self.end_date, "%Y-%m-%d"
        )
        if end <= start:
            raise ValueError("End date must be after start date")
        return self


class WalkForwardRequest(V2BacktestRequest):
    """Request for a rolling walk-forward experiment."""

    param_grid: dict[str, list[float | int]] = Field(
        ..., description="Parameter name -> candidate values (cartesian product is tested)"
    )
    train_bars: int = Field(..., ge=50, description="Training window size in bars")
    test_bars: int = Field(..., ge=10, description="Test window size in bars")
    selection_metric: Literal["sharpe", "cagr"] = Field(
        default="sharpe", description="Metric maximized on the train segment"
    )


@router.post("/v2/run")
async def run_backtest_v2(request: V2BacktestRequest) -> dict:
    """V2 backtest: fills at the next bar's open with full costs, benchmark
    comparison, the complete metric suite and a reproducibility manifest."""
    from time import time

    start_time = time()
    try:
        service = BacktestService()
        result = await service.run_backtest_v2(
            symbol=request.symbol,
            strategy=request.strategy,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_cash=request.initial_cash,
            market=request.market,
            strategy_params=request.strategy_params,
            benchmark_symbol=request.benchmark_symbol,
        )
        result["execution_time"] = round(time() - start_time, 3)
        return result
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        logger.error(f"V2 backtest failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/v2/walkforward")
async def run_walk_forward(request: WalkForwardRequest) -> dict:
    """Rolling walk-forward: parameters chosen on train, scored on unseen test
    windows; reports every window (including losers) and configs tested."""
    from time import time

    start_time = time()
    try:
        service = BacktestService()
        result = await service.run_walk_forward(
            symbol=request.symbol,
            strategy=request.strategy,
            start_date=request.start_date,
            end_date=request.end_date,
            param_grid=request.param_grid,
            train_bars=request.train_bars,
            test_bars=request.test_bars,
            initial_cash=request.initial_cash,
            market=request.market,
            selection_metric=request.selection_metric,
        )
        result["execution_time"] = round(time() - start_time, 3)
        return result
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        logger.error(f"Walk-forward failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


class CalibrateRequest(BaseModel):
    """Request for historical signal hit-rate calibration."""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(..., description="Stock symbol to calibrate on")
    strategy: Literal["sma_crossover", "rsi_strategy", "macd_strategy", "buy_and_hold"] = Field(
        ..., description="Strategy whose entry signals are calibrated"
    )
    start_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    horizons: list[int] = Field(
        default=[20, 60], description="Forward horizons in bars for hit measurement"
    )
    benchmark_symbol: str | None = Field(
        default=None, description="Hits are measured as excess over this benchmark"
    )
    strategy_params: dict[str, float | int] = Field(default_factory=dict)

    @field_validator("symbol")
    @classmethod
    def _validate_symbol(cls, value: str) -> str:
        if not validate_stock_symbol(value):
            raise ValueError(f"Invalid stock symbol: {value}")
        return value.upper()

    @field_validator("benchmark_symbol")
    @classmethod
    def _validate_benchmark(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned or any(ch.isspace() for ch in cleaned):
            raise ValueError(f"Invalid benchmark symbol: {value}")
        return cleaned

    @field_validator("horizons")
    @classmethod
    def _validate_horizons(cls, value: list[int]) -> list[int]:
        if not value or any(h <= 0 or h > 750 for h in value):
            raise ValueError("horizons must be within 1..750 bars")
        return value


@router.post("/v2/calibrate")
async def calibrate_signals(request: CalibrateRequest) -> dict:
    """Empirical hit rates of the strategy's entry signals per horizon, with
    Wilson lower bounds and per-year breakdowns — the grounding for any
    reported confidence."""
    from time import time

    start_time = time()
    try:
        service = BacktestService()
        result = await service.calibrate_signals(
            symbol=request.symbol,
            strategy=request.strategy,
            start_date=request.start_date,
            end_date=request.end_date,
            horizons=request.horizons,
            benchmark_symbol=request.benchmark_symbol,
            strategy_params=request.strategy_params,
        )
        result["execution_time"] = round(time() - start_time, 3)
        return result
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        logger.error(f"Calibration failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
