"""Backtesting service for trading strategies."""

from datetime import datetime
from typing import Any, Dict, List, Optional

import backtrader as bt
import numpy as np
import pandas as pd
import yfinance as yf

from app.utils.logging import get_logger

logger = get_logger(__name__)


class BacktestService:
    """Service for backtesting trading strategies.

    Supports:
    - Multiple built-in strategies
    - Custom strategy parameters
    - Performance metrics calculation
    - Strategy comparison
    """

    async def run_backtest(
        self,
        symbol: str,
        strategy: str,
        start_date: str,
        end_date: str,
        initial_cash: float = 10000.0,
        commission: float = 0.001,
        strategy_params: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Run a backtest for the given strategy.

        Args:
            symbol: Stock symbol
            strategy: Strategy name
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            initial_cash: Initial cash amount
            commission: Commission rate
            strategy_params: Optional strategy parameters

        Returns:
            Backtest results dictionary
        """
        logger.info(
            f"Running backtest: {symbol} {strategy} from {start_date} to {end_date}"
        )

        try:
            # Fetch historical data
            data = await self._fetch_data(symbol, start_date, end_date)

            if data.empty:
                raise ValueError(f"No data available for {symbol}")

            # Create cerebro instance
            cerebro = bt.Cerebro()

            # Add data feed
            cerebro.adddata(bt.feeds.PandasData(dataname=data))

            # Set initial cash and commission
            cerebro.broker.setcash(initial_cash)
            cerebro.broker.setcommission(commission=commission)

            # Add strategy
            strategy_class = self._get_strategy(strategy)
            cerebro.addstrategy(
                strategy_class,
                **(strategy_params or {})
            )

            # Add analyzers
            cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
            cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
            cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

            # Run backtest
            results = cerebro.run()
            strat = results[0]

            # Extract results
            final_value = cerebro.broker.getvalue()
            total_return = final_value - initial_cash
            total_return_pct = (total_return / initial_cash) * 100

            # Get analyzer results
            sharpe = strat.analyzers.sharpe.get_analysis()
            drawdown = strat.analyzers.drawdown.get_analysis()
            trades = strat.analyzers.trades.get_analysis()

            # Calculate metrics
            sharpe_ratio = sharpe.get("sharperatio") if sharpe else None
            max_drawdown = drawdown.get("max", {}).get("drawdown", 0) if drawdown else 0

            # Trade statistics
            total_trades = 0
            won_trades = 0
            lost_trades = 0

            if trades and "total" in trades and "won" in trades and "lost" in trades:
                total_trades = trades.get("total", {}).get("total", 0)
                won_trades = trades.get("won", {}).get("total", 0)
                lost_trades = trades.get("lost", {}).get("total", 0)

            win_rate = (won_trades / total_trades * 100) if total_trades > 0 else 0

            # Calculate annual return (simplified)
            days = (data.index[-1] - data.index[0]).days
            years = days / 365.25 if days > 0 else 1
            annual_return = ((final_value / initial_cash) ** (1 / years) - 1) * 100

            return {
                "symbol": symbol,
                "strategy": strategy,
                "initial_cash": initial_cash,
                "final_value": final_value,
                "total_return": total_return,
                "total_return_pct": total_return_pct,
                "annual_return": annual_return,
                "sharpe_ratio": sharpe_ratio or 0,
                "max_drawdown": abs(max_drawdown),
                "win_rate": win_rate,
                "total_trades": total_trades,
                "won_trades": won_trades,
                "lost_trades": lost_trades,
                "trades_list": strat.trades if hasattr(strat, "trades") else [],
            }

        except Exception as e:
            logger.error(f"Backtest failed: {e}")
            raise

    async def _fetch_data(
        self, symbol: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
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

    def _get_strategy(self, strategy_name: str) -> type:
        """Get strategy class by name.

        Args:
            strategy_name: Name of the strategy

        Returns:
            Strategy class
        """
        strategies = {
            "sma_crossover": SMACrossoverStrategy,
            "rsi_strategy": RSIStrategy,
            "macd_strategy": MACDStrategy,
            "buy_and_hold": BuyAndHoldStrategy,
        }

        if strategy_name not in strategies:
            raise ValueError(f"Unknown strategy: {strategy_name}")

        return strategies[strategy_name]


# Backtrader Strategies

class SMACrossoverStrategy(bt.Strategy):
    """Simple Moving Average Crossover Strategy."""

    params = (
        ("sma_short", 20),
        ("sma_long", 50),
    )

    def __init__(self):
        """Initialize the strategy."""
        self.sma_short = bt.indicators.SMA(self.data.close, period=self.params.sma_short)
        self.sma_long = bt.indicators.SMA(self.data.close, period=self.params.sma_long)
        self.crossover = bt.indicators.CrossOver(self.sma_short, self.sma_long)

        self.trades = []

    def next(self):
        """Execute trading logic on each bar."""
        if not self.position:
            if self.crossover > 0:  # Short crosses above Long
                self.buy()
                self.trades.append({
                    "type": "buy",
                    "date": self.data.datetime.date(0).isoformat(),
                    "price": self.data.close[0],
                })
        else:
            if self.crossover < 0:  # Short crosses below Long
                self.sell()
                self.trades.append({
                    "type": "sell",
                    "date": self.data.datetime.date(0).isoformat(),
                    "price": self.data.close[0],
                })


class RSIStrategy(bt.Strategy):
    """RSI Overbought/Oversold Strategy."""

    params = (
        ("rsi_period", 14),
        ("rsi_overbought", 70),
        ("rsi_oversold", 30),
    )

    def __init__(self):
        """Initialize the strategy."""
        self.rsi = bt.indicators.RSI(self.data.close, period=self.params.rsi_period)
        self.trades = []

    def next(self):
        """Execute trading logic on each bar."""
        if not self.position:
            if self.rsi < self.params.rsi_oversold:
                self.buy()
                self.trades.append({
                    "type": "buy",
                    "date": self.data.datetime.date(0).isoformat(),
                    "price": self.data.close[0],
                    "rsi": self.rsi[0],
                })
        else:
            if self.rsi > self.params.rsi_overbought:
                self.sell()
                self.trades.append({
                    "type": "sell",
                    "date": self.data.datetime.date(0).isoformat(),
                    "price": self.data.close[0],
                    "rsi": self.rsi[0],
                })


class MACDStrategy(bt.Strategy):
    """MACD Signal Line Crossover Strategy."""

    params = (
        ("fast_period", 12),
        ("slow_period", 26),
        ("signal_period", 9),
    )

    def __init__(self):
        """Initialize the strategy."""
        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=self.params.fast_period,
            period_me2=self.params.slow_period,
            period_signal=self.params.signal_period,
        )
        self.trades = []

    def next(self):
        """Execute trading logic on each bar."""
        if not self.position:
            if self.macd.macd[0] > self.macd.signal[0]:
                self.buy()
                self.trades.append({
                    "type": "buy",
                    "date": self.data.datetime.date(0).isoformat(),
                    "price": self.data.close[0],
                })
        else:
            if self.macd.macd[0] < self.macd.signal[0]:
                self.sell()
                self.trades.append({
                    "type": "sell",
                    "date": self.data.datetime.date(0).isoformat(),
                    "price": self.data.close[0],
                })


class BuyAndHoldStrategy(bt.Strategy):
    """Buy and Hold Benchmark Strategy."""

    def __init__(self):
        """Initialize the strategy."""
        self.trades = []

    def next(self):
        """Execute trading logic on each bar."""
        if not self.position:
            self.buy()
            self.trades.append({
                "type": "buy",
                "date": self.data.datetime.date(0).isoformat(),
                "price": self.data.close[0],
            })
