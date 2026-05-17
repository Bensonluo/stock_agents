"""Market data tool with multi-source fallback."""

import asyncio
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.tools.data.fetcher import fetch_stock_data
from app.utils.logging import get_logger

logger = get_logger(__name__)

_semaphore = asyncio.Semaphore(5)


class FetchStockDataInput(BaseModel):
    symbols: list[str] = Field(description="Stock ticker symbols (e.g., ['AAPL', '601888'])")
    source: str = Field(default="auto", description="Data source: ignored, uses multi-source fallback")


@tool(args_schema=FetchStockDataInput)
async def fetch_stock_data_tool(symbols: list[str], source: str = "auto") -> dict[str, Any]:
    """Fetch real-time and historical stock market data, financials, and news.

    This is the FIRST tool you should call. It provides the raw data needed
    for all other analysis tools. Automatically tries multiple data sources
    if one fails.
    """
    async with _semaphore:
        tasks = [fetch_stock_data(s) for s in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    output = {}
    for symbol, result in zip(symbols, results):
        if isinstance(result, Exception):
            logger.error(f"Failed to fetch data for {symbol}: {result}")
            continue
        if result:
            output[symbol] = result

    return output if output else {"error": "No data retrieved for any symbol", "symbols": symbols}


# Keep the old name as alias for backward compatibility with registered tools
fetch_stock_data = fetch_stock_data_tool
