"""Backtesting service for trading strategies."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any

import pandas as pd
import yfinance as yf

from app.backtest import (
    CN_STOCK,
    STRATEGIES,
    STRATEGY_PARAMETERS,
    US_STOCK,
    CostModel,
    build_manifest,
)
from app.backtest import (
    run_backtest as run_v2_engine,
)
from app.backtest import (
    walk_forward as walk_forward_engine,
)
from app.backtest.null_benchmark import NULL_ITERATIONS
from app.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

# The engine is a CPU-bound bar-by-bar loop; running it inline in the event
# loop stalls every HTTP/WebSocket/analysis task sharing the worker (the
# default 300-draw null benchmark alone blocks for seconds on ~2,500 bars).
# A dedicated bounded pool means concurrent backtests queue instead of
# fanning out onto the shared default executor.
_BACKTEST_EXECUTOR = ThreadPoolExecutor(
    max_workers=settings.backtest_executor_workers, thread_name_prefix="backtest"
)


async def _run_engine(fn, /, *args, **kwargs):
    """Await a sync engine call on the dedicated bounded backtest pool.

    ``fn`` is bound into the ``partial`` at call time from the module's
    namespace, so tests monkeypatching ``app.services.backtest_service``
    names keep working.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_BACKTEST_EXECUTOR, partial(fn, *args, **kwargs))


def _series_to_points(series: pd.Series | None) -> list[dict[str, float | str]] | None:
    """Equity curve as JSON points; None passes through."""
    if series is None:
        return None
    return [{"date": str(date), "value": round(float(value), 6)} for date, value in series.items()]


class BacktestService:
    """Service for backtesting trading strategies.

    Supports:
    - Multiple built-in strategies
    - Custom strategy parameters
    - Performance metrics calculation
    - Strategy comparison
    """

    # Single source of truth: the engine's canonical strategy→parameter
    # registry (module import). A hand-maintained copy used to live here and
    # omitted technical_score, so the legacy endpoint rejected every
    # score_threshold request with a 500.
    STRATEGY_PARAMETERS = STRATEGY_PARAMETERS

    async def run_backtest(
        self,
        symbol: str,
        strategy: str,
        start_date: str,
        end_date: str,
        initial_cash: float = 10000.0,
        commission: float = 0.001,
        strategy_params: dict | None = None,
    ) -> dict[str, Any]:
        """Run a backtest via the V2 deterministic engine (legacy response shape).

        Kept for the existing ``POST /run`` contract: fills at the next bar's
        open, costs via ``commission``, force-liquidation at the final close.
        The old Backtrader implementation was retired — one engine, one truth.

        Args:
            symbol: Stock symbol to backtest
            strategy: Strategy name
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            initial_cash: Initial cash amount
            commission: Commission rate (per side)
            strategy_params: Optional strategy parameters

        Returns:
            Backtest results dictionary (legacy field names)
        """
        logger.info(f"Running backtest: {symbol} {strategy} from {start_date} to {end_date}")

        data = await self._fetch_data(symbol, start_date, end_date)
        if data.empty:
            raise ValueError(f"No data available for {symbol}")

        selected_params = self._get_strategy_params(strategy, strategy_params)
        result = await _run_engine(
            run_v2_engine,
            data,
            strategy=strategy,
            cost_model=CostModel(commission_rate=commission),
            initial_cash=initial_cash,
            null_iterations=NULL_ITERATIONS,
            **selected_params,
        )

        final_value = float(result.equity.iloc[-1])
        total_return = final_value - initial_cash
        sells = [trade for trade in result.trades if trade.get("action") == "sell"]
        won = [trade for trade in sells if (trade.get("pnl") or 0) > 0]
        lost = [trade for trade in sells if (trade.get("pnl") or 0) <= 0]
        metrics = result.metrics
        cagr = metrics.get("cagr")
        years = max(len(result.equity) / 252, 1e-9)

        return {
            "symbol": symbol,
            "strategy": strategy,
            "initial_cash": initial_cash,
            "final_value": final_value,
            "total_return": total_return,
            "total_return_pct": (total_return / initial_cash) * 100,
            "annual_return": (
                ((final_value / initial_cash) ** (1 / years) - 1) * 100
                if cagr is None
                else cagr * 100
            ),
            "sharpe_ratio": metrics.get("sharpe") or 0,
            "max_drawdown": (metrics.get("max_drawdown") or 0) * 100,
            "win_rate": (metrics.get("win_rate") or 0) * 100,
            "total_trades": int(metrics.get("total_trades") or 0),
            "won_trades": len(won),
            "lost_trades": len(lost),
            "trades_list": result.trades,
            "equity": _series_to_points(result.equity) or [],
            "null_benchmark": result.null_benchmark,
        }

    async def run_backtest_v2(
        self,
        symbol: str,
        strategy: str,
        start_date: str,
        end_date: str,
        initial_cash: float = 10_000.0,
        market: str = "us",
        strategy_params: dict | None = None,
        benchmark_symbol: str | None = None,
        null_iterations: int = NULL_ITERATIONS,
    ) -> dict[str, Any]:
        """V2-engine backtest: next-bar fills, full costs, benchmark, manifest."""
        data = await self._fetch_data(symbol, start_date, end_date)
        benchmark_data = None
        if benchmark_symbol:
            benchmark_data = await self._fetch_data(benchmark_symbol, start_date, end_date)

        result = await _run_engine(
            run_v2_engine,
            data,
            strategy=strategy,
            cost_model=self._cost_model(market),
            initial_cash=initial_cash,
            benchmark_data=benchmark_data,
            null_iterations=null_iterations,
            **(strategy_params or {}),
        )
        manifest = build_manifest(
            symbol=symbol,
            strategy=strategy,
            params=result.params,
            start=start_date,
            end=end_date,
            data=data,
            cost_model=self._cost_model(market),
        )
        return {
            "symbol": symbol,
            "strategy": strategy,
            "params": result.params,
            "period": {"start": start_date, "end": end_date},
            "bars": result.bars,
            "initial_cash": initial_cash,
            "metrics": result.metrics,
            "equity": _series_to_points(result.equity),
            "benchmark_equity": (
                _series_to_points(result.benchmark_equity)
                if result.benchmark_equity is not None
                else None
            ),
            "trades": result.trades,
            "manifest": manifest,
            "null_benchmark": result.null_benchmark,
        }

    async def run_walk_forward(
        self,
        symbol: str,
        strategy: str,
        start_date: str,
        end_date: str,
        param_grid: dict[str, list],
        train_bars: int,
        test_bars: int,
        initial_cash: float = 10_000.0,
        market: str = "us",
        selection_metric: str = "sharpe",
    ) -> dict[str, Any]:
        """Rolling walk-forward: pick params on train, score unseen test windows."""
        data = await self._fetch_data(symbol, start_date, end_date)
        report = await _run_engine(
            walk_forward_engine,
            data,
            strategy=strategy,
            param_grid=param_grid,
            train_bars=train_bars,
            test_bars=test_bars,
            cost_model=self._cost_model(market),
            initial_cash=initial_cash,
            selection_metric=selection_metric,
        )
        report["manifest"] = build_manifest(
            symbol=symbol,
            strategy=strategy,
            params={"grid": param_grid},
            start=start_date,
            end=end_date,
            data=data,
            cost_model=self._cost_model(market),
            configs_tested=report.get("configs_tested", 0),
        )
        return report

    async def calibrate_signals(
        self,
        symbol: str,
        strategy: str,
        start_date: str,
        end_date: str,
        horizons: list[int] | None = None,
        benchmark_symbol: str | None = None,
        strategy_params: dict | None = None,
    ) -> dict[str, Any]:
        """Empirical hit rates of the strategy's entry signals, per horizon."""
        from app.backtest import calibrate_signals as calibrate_engine

        data = await self._fetch_data(symbol, start_date, end_date)
        benchmark_data = None
        if benchmark_symbol:
            benchmark_data = await self._fetch_data(benchmark_symbol, start_date, end_date)

        report = await _run_engine(
            calibrate_engine,
            data,
            strategy=strategy,
            horizons=tuple(horizons or (20, 60)),
            benchmark_data=benchmark_data,
            **(strategy_params or {}),
        )
        report["manifest"] = build_manifest(
            symbol=symbol,
            strategy=strategy,
            params=report["params"],
            start=start_date,
            end=end_date,
            data=data,
            cost_model=self._cost_model("us"),
        )
        return report

    @staticmethod
    def _cost_model(market: str) -> CostModel:
        preset = {"cn": CN_STOCK, "us": US_STOCK}.get(str(market).lower())
        if preset is None:
            raise ValueError(f"Unknown market preset: {market} (use 'cn' or 'us')")
        return preset

    async def _fetch_data(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Fetch historical data for backtesting.

        Primary path is the direct yfinance snapshot; when it fails (CN servers
        are frequently rate-limited by Yahoo), fall back to the shared
        multi-source chain (yfinance -> finnhub -> akshare -> yahoo-api ->
        stooq) and slice it to the requested window.

        Args:
            symbol: Stock symbol
            start_date: Start date
            end_date: End date

        Returns:
            DataFrame with OHLCV data
        """
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(start=start_date, end=end_date)

            if df.empty:
                raise ValueError(f"No data found for {symbol}")

            # Ensure required columns exist
            required_cols = ["Open", "High", "Low", "Close", "Volume"]
            for col in required_cols:
                if col not in df.columns:
                    raise ValueError(f"Missing required column: {col}")

            if not df.empty:
                return df
            logger.warning(
                f"[backtest] yfinance returned no rows for {symbol}; trying provider chain"
            )

        except Exception as e:
            logger.warning(f"[backtest] yfinance failed for {symbol}: {e}; trying provider chain")

        return await self._fetch_data_via_chain(symbol, start_date, end_date)

    async def _fetch_data_via_chain(
        self, symbol: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """Shared provider chain fallback, sliced to the requested window."""
        from app.tools.data.fetcher import fetch_historical

        hist = await fetch_historical(symbol)
        if not isinstance(hist, dict) or not hist.get("dates"):
            raise ValueError(f"No data available for {symbol}")

        closes = hist.get("close") or []
        index = pd.to_datetime(hist["dates"])
        frame = pd.DataFrame(
            {
                "Open": hist.get("open") or closes,
                "High": hist.get("high") or closes,
                "Low": hist.get("low") or closes,
                "Close": closes,
                "Volume": hist.get("volume") or [0.0] * len(closes),
            },
            index=index,
        ).sort_index()
        window = frame.loc[(frame.index >= start_date) & (frame.index <= end_date)]
        if window.empty:
            raise ValueError(f"No data available for {symbol} in {start_date}..{end_date}")
        logger.info(f"[backtest] provider chain supplied {len(window)} bars for {symbol}")
        return window

    def _get_strategy_params(self, strategy_name: str, strategy_params: dict | None = None) -> dict:
        """Validate and select only parameters supported by a strategy.

        Known parameters for other strategies are ignored so callers may safely
        pass a shared parameter collection. Unknown names are rejected to surface
        misspellings instead of silently running with an unintended default.
        """
        if strategy_name not in STRATEGIES:
            raise ValueError(f"Unknown strategy: {strategy_name}")
        provided_params = strategy_params or {}
        known_params = set().union(*self.STRATEGY_PARAMETERS.values())
        unknown_params = set(provided_params) - known_params
        if unknown_params:
            unknown = sorted(unknown_params)[0]
            raise ValueError(f"Unknown strategy parameter: {unknown}")

        accepted_params = self.STRATEGY_PARAMETERS[strategy_name]
        return {
            name: value
            for name, value in provided_params.items()
            if name in accepted_params and value is not None
        }
