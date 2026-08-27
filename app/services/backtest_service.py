"""Backtesting service for trading strategies."""

from typing import Any

import pandas as pd
import yfinance as yf

from app.backtest import (
    CN_STOCK,
    STRATEGIES,
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
from app.utils.logging import get_logger

logger = get_logger(__name__)


def _series_to_points(series: pd.Series | None) -> list[dict[str, float | str]] | None:
    """Equity curve as JSON points; None passes through."""
    if series is None:
        return None
    return [
        {"date": str(date), "value": round(float(value), 6)}
        for date, value in series.items()
    ]


class BacktestService:
    """Service for backtesting trading strategies.

    Supports:
    - Multiple built-in strategies
    - Custom strategy parameters
    - Performance metrics calculation
    - Strategy comparison
    """

    STRATEGY_PARAMETERS = {
        "sma_crossover": frozenset({"sma_short", "sma_long"}),
        "rsi_strategy": frozenset({"rsi_period", "rsi_overbought", "rsi_oversold"}),
        "macd_strategy": frozenset({"fast_period", "slow_period", "signal_period"}),
        "buy_and_hold": frozenset(),
    }

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
        result = run_v2_engine(
            data,
            strategy=strategy,
            cost_model=CostModel(commission_rate=commission),
            initial_cash=initial_cash,
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
            "annual_return": ((final_value / initial_cash) ** (1 / years) - 1) * 100
            if cagr is None
            else cagr * 100,
            "sharpe_ratio": metrics.get("sharpe") or 0,
            "max_drawdown": (metrics.get("max_drawdown") or 0) * 100,
            "win_rate": (metrics.get("win_rate") or 0) * 100,
            "total_trades": int(metrics.get("total_trades") or 0),
            "won_trades": len(won),
            "lost_trades": len(lost),
            "trades_list": result.trades,
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
    ) -> dict[str, Any]:
        """V2-engine backtest: next-bar fills, full costs, benchmark, manifest."""
        data = await self._fetch_data(symbol, start_date, end_date)
        benchmark_data = None
        if benchmark_symbol:
            benchmark_data = await self._fetch_data(benchmark_symbol, start_date, end_date)

        result = run_v2_engine(
            data,
            strategy=strategy,
            cost_model=self._cost_model(market),
            initial_cash=initial_cash,
            benchmark_data=benchmark_data,
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
            "benchmark_equity": _series_to_points(result.benchmark_equity)
            if result.benchmark_equity is not None
            else None,
            "trades": result.trades,
            "manifest": manifest,
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
        report = walk_forward_engine(
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

        report = calibrate_engine(
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

            return df

        except Exception as e:
            logger.error(f"Error fetching data for {symbol}: {e}")
            raise

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
