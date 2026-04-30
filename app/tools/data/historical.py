"""Historical price data tool."""

from typing import Any

import yfinance as yf
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.utils.logging import get_logger

logger = get_logger(__name__)


class GetHistoricalPricesInput(BaseModel):
    symbol: str = Field(description="Stock symbol (e.g., 'AAPL', '601888.SS')")
    period: str = Field(default="3mo", description="Time period: '1d', '5d', '1mo', '3mo', '6mo', '1y', '2y', '5y', '10y', 'ytd', 'max'")
    interval: str = Field(default="1d", description="Data interval: '1d', '1wk', '1mo'")


@tool(args_schema=GetHistoricalPricesInput)
async def get_historical_prices(
    symbol: str,
    period: str = "3mo",
    interval: str = "1d",
) -> dict[str, Any]:
    """Get historical price data for a stock.

    Use this when you need extended price history for backtesting or detailed
    chart analysis beyond what fetch_stock_data provides.

    Args:
        symbol: Stock symbol
        period: Time period (e.g., '1mo', '3mo', '1y')
        interval: Data interval ('1d' for daily, '1wk' for weekly)

    Returns:
        Dictionary with dates, open, high, low, close, volume arrays.
    """
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period, interval=interval)

        if hist.empty:
            return {"error": f"No historical data found for {symbol}"}

        return {
            "symbol": symbol,
            "period": period,
            "interval": interval,
            "dates": [d.strftime("%Y-%m-%d") for d in hist.index],
            "open": hist["Open"].tolist(),
            "high": hist["High"].tolist(),
            "low": hist["Low"].tolist(),
            "close": hist["Close"].tolist(),
            "volume": hist["Volume"].tolist(),
        }

    except Exception as e:
        logger.error(f"Error fetching historical prices for {symbol}: {e}")
        return {"error": str(e)}
