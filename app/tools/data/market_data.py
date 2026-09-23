"""Market data tool with multi-source fallback."""

import asyncio
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.tools.data.fetcher import fetch_stock_data as fetch_stock_data_from_providers
from app.utils.logging import get_logger

logger = get_logger(__name__)

_semaphore = asyncio.Semaphore(5)


class FetchStockDataInput(BaseModel):
    symbols: list[str] = Field(description="Stock ticker symbols (e.g., ['AAPL', '601888'])")
    source: str = Field(
        default="auto", description="Data source: ignored, uses multi-source fallback"
    )


@tool(args_schema=FetchStockDataInput)
async def fetch_stock_data_tool(symbols: list[str], source: str = "auto") -> dict[str, Any]:
    """Fetch real-time and historical stock market data, financials, and news.

    This is the FIRST tool you should call. It provides the raw data needed
    for all other analysis tools. Automatically tries multiple data sources
    if one fails.
    """
    # Failure circuit-breaker shared with the analyze tools: once a symbol's
    # provider chain has failed repeatedly, refuse WITHOUT hitting providers —
    # the ReAct retry loop otherwise burns quota on calls that cannot succeed.
    from app.tools.analysis.auto_tools import (
        _fetch_failures_exceeded,
        _record_fetch_failure,
        _reset_fetch_failures,
        data_unavailable_error,
    )

    blocked = [s for s in symbols if _fetch_failures_exceeded(s)]
    if blocked:
        return data_unavailable_error(blocked[0])

    async with _semaphore:
        tasks = [fetch_stock_data_from_providers(s) for s in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    output = {}
    for symbol, result in zip(symbols, results):
        if isinstance(result, Exception):
            logger.error(f"Failed to fetch data for {symbol}: {result}")
            continue
        if result:
            output[symbol] = result
            _reset_fetch_failures(symbol)

    if output:
        return output
    for s in symbols:
        _record_fetch_failure(s)
    first = symbols[0] if symbols else ""
    count = None
    from app.tools.analysis.auto_tools import _fetch_failures

    count = _fetch_failures.get(first, (0, 0.0))[0]
    if count >= 2:
        return data_unavailable_error(first)
    return {"error": "No data retrieved for any symbol", "symbols": symbols}


# Keep the old name as alias for backward compatibility with registered tools
fetch_stock_data = fetch_stock_data_tool
