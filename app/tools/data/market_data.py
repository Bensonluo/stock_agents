"""Data collection tools for the ReAct agent.

Extracted from app/agents/data_agent.py
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import yfinance as yf
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.utils.logging import get_logger

logger = get_logger(__name__)


def _convert_to_yahoo_symbol(symbol: str) -> str:
    """Convert local symbol to Yahoo Finance format."""
    if symbol.isalpha() and len(symbol) <= 5:
        return symbol
    if ".HK" in symbol.upper():
        return symbol.upper()
    if symbol.isdigit() and len(symbol) == 6:
        if symbol.startswith("6"):
            return f"{symbol}.SS"
        elif symbol.startswith("0") or symbol.startswith("3"):
            return f"{symbol}.SZ"
        return f"{symbol}.SS"
    return symbol


def _historical_data_to_dict(df: pd.DataFrame) -> dict:
    """Convert historical DataFrame to dict."""
    if df is None or df.empty:
        return {}
    return {
        "dates": [d.strftime("%Y-%m-%d") for d in df.index],
        "open": df["Open"].tolist(),
        "high": df["High"].tolist(),
        "low": df["Low"].tolist(),
        "close": df["Close"].tolist(),
        "volume": df["Volume"].tolist(),
    }


def _financial_statement_to_dict(df: pd.DataFrame) -> dict:
    """Convert financial statement DataFrame to dict."""
    if df is None or df.empty:
        return {}
    return {
        "dates": [d.strftime("%Y-%m-%d") for d in df.columns],
        "data": {row: df.loc[row].tolist() for row in df.index},
    }


class FetchStockDataInput(BaseModel):
    symbols: list[str] = Field(description="Stock ticker symbols (e.g., ['AAPL', '601888'])")
    source: str = Field(default="auto", description="Data source: 'yfinance', 'akshare', or 'auto'")


@tool(args_schema=FetchStockDataInput)
async def fetch_stock_data(symbols: list[str], source: str = "auto") -> dict[str, Any]:
    """Fetch real-time and historical stock market data, financials, and news.

    This is the FIRST tool you should call. It provides the raw data needed
    for all other analysis tools.

    Args:
        symbols: List of stock symbols (e.g., ['AAPL', '601888.SS', '0700.HK'])
        source: Data source - use 'auto' to let the system decide

    Returns:
        Dictionary mapping each symbol to its market data, financial data, and news.
    """
    tasks = [_fetch_single_symbol_data(s) for s in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    output = {}
    for symbol, result in zip(symbols, results):
        if isinstance(result, Exception):
            logger.error(f"Failed to fetch data for {symbol}: {result}")
            continue
        if result:
            output[symbol] = result

    return output


async def _fetch_single_symbol_data(symbol: str) -> dict[str, Any] | None:
    """Fetch all data for a single symbol."""
    try:
        yahoo_symbol = _convert_to_yahoo_symbol(symbol)
        ticker = yf.Ticker(yahoo_symbol)

        info = ticker.info
        end_date = datetime.now()
        start_date = end_date - timedelta(days=90)
        hist = ticker.history(start=start_date, end=end_date)

        market_data = {}
        if not hist.empty:
            market_data = {
                "symbol": symbol,
                "yahoo_symbol": yahoo_symbol,
                "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
                "previous_close": info.get("previousClose"),
                "change": info.get("currentPrice") - info.get("previousClose", 0)
                if info.get("currentPrice") and info.get("previousClose")
                else None,
                "change_percent": (
                    (info.get("currentPrice") - info.get("previousClose", 0))
                    / info.get("previousClose", 1) * 100
                    if info.get("currentPrice") and info.get("previousClose")
                    else None
                ),
                "volume": info.get("volume"),
                "avg_volume": info.get("averageVolume"),
                "market_cap": info.get("marketCap"),
                "52_week_high": info.get("fiftyTwoWeekHigh"),
                "52_week_low": info.get("fiftyTwoWeekLow"),
                "company_name": info.get("longName"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "historical_data": _historical_data_to_dict(hist),
            }

        # Financial data
        financial_data = {}
        try:
            financial_data = {
                "metrics": {
                    "roe": info.get("returnOnEquity"),
                    "roa": info.get("returnOnAssets"),
                    "profit_margin": info.get("profitMargins"),
                    "operating_margin": info.get("operatingMargins"),
                    "pe_ratio": info.get("trailingPE"),
                    "forward_pe": info.get("forwardPE"),
                    "pb_ratio": info.get("priceToBook"),
                    "ps_ratio": info.get("priceToSalesTrailing12Months"),
                    "peg_ratio": info.get("pegRatio"),
                    "enterprise_value": info.get("enterpriseValue"),
                    "ev_ebitda": info.get("enterpriseToEbitda"),
                    "debt_to_equity": info.get("debtToEquity"),
                    "current_ratio": info.get("currentRatio"),
                    "quick_ratio": info.get("quickRatio"),
                    "total_cash": info.get("totalCash"),
                    "total_debt": info.get("totalDebt"),
                    "total_revenue": info.get("totalRevenue"),
                    "dividend_yield": info.get("dividendYield"),
                    "payout_ratio": info.get("payoutRatio"),
                }
            }
        except Exception:
            pass

        # News
        news_data = []
        try:
            raw_news = ticker.news
            for item in (raw_news or [])[:20]:
                content = item.get("content", {})
                title = content.get("title") or item.get("title")
                summary = content.get("summary") or item.get("summary")
                link = None
                if content.get("canonicalUrl"):
                    link = content["canonicalUrl"].get("url")
                if not link and item.get("link"):
                    link = item.get("link")

                provider = content.get("provider", {})
                source_name = provider.get("displayName") or item.get("publisher")
                published = content.get("pubDate") or item.get("providerPublishTime")

                related = item.get("relatedTickers", [])
                if symbol not in related:
                    related.append(symbol)

                if title:
                    news_data.append({
                        "title": title,
                        "link": link,
                        "published": published,
                        "source": source_name,
                        "summary": summary,
                        "related_symbols": related,
                        "original_symbol": symbol,
                    })
        except Exception:
            pass

        return {
            "market_data": market_data,
            "financial_data": financial_data,
            "news_data": news_data,
        }

    except Exception as e:
        logger.error(f"Error collecting data for {symbol}: {e}")
        return None
