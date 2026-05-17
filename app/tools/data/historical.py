"""Historical price data tool with multi-source fallback."""

from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.tools.data.fetcher import fetch_historical
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

    Automatically tries multiple data sources (yfinance, akshare, Yahoo API)
    if the primary source fails.
    """
    result = await fetch_historical(symbol, period)

    if "error" in result:
        return result

    result["interval"] = interval
    return result
