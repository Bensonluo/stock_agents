"""Data collection agent for fetching stock market data."""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
import yfinance as yf

from app.agents.base import BaseAgent
from app.orchestration.state import AgentState
from app.utils.logging import get_logger

logger = get_logger(__name__)


def convert_to_yahoo_symbol(symbol: str) -> str:
    """Convert local symbol format to Yahoo Finance format.

    Args:
        symbol: Stock symbol in various formats

    Returns:
        Yahoo Finance compatible symbol

    Examples:
        601888 -> 601888.SS (Shanghai)
        000001 -> 000001.SZ (Shenzhen)
        300001 -> 300001.SZ (Shenzhen ChiNext)
        AAPL -> AAPL (US stocks unchanged)
        3690.HK -> 3690.HK (HK stocks unchanged)
    """
    # US stocks (1-5 letters) - unchanged
    if symbol.isalpha() and len(symbol) <= 5:
        return symbol

    # HK stocks - unchanged
    if ".HK" in symbol.upper():
        return symbol.upper()

    # Chinese stocks (6 digits) - add exchange suffix
    if symbol.isdigit() and len(symbol) == 6:
        if symbol.startswith("6"):
            # Shanghai Stock Exchange (600xxx, 601xxx, 603xxx, 605xxx)
            return f"{symbol}.SS"
        elif symbol.startswith("0") or symbol.startswith("3"):
            # Shenzhen Stock Exchange (000xxx, 001xxx, 002xxx, 003xxx) or ChiNext (300xxx)
            return f"{symbol}.SZ"
        else:
            # Default to Shanghai for other codes
            return f"{symbol}.SS"

    return symbol


def detect_symbol_type(symbol: str) -> str:
    """Detect the type/market of a stock symbol.

    Args:
        symbol: Stock symbol

    Returns:
        Market type: 'us', 'cn', 'hk', or 'unknown'
    """
    s = symbol.upper()

    # US stocks: 1-5 letters
    if s.isalpha() and len(s) <= 5:
        return "us"

    # HK stocks: digits + .HK
    if ".HK" in s:
        return "hk"

    # Chinese stocks: 6 digits
    if s.isdigit() and len(s) == 6:
        return "cn"

    return "unknown"


class DataCollectionAgent(BaseAgent):
    """Agent responsible for collecting stock market data.

    This agent:
    - Fetches real-time and historical price data
    - Collects financial data (income statement, balance sheet, cash flow)
    - Gathers news and sentiment data
    - Normalizes and cleans data from multiple sources

    Data sources:
    - yfinance: Free source for US and international stocks
    - AkShare: Can be added for Chinese market data
    """

    async def execute(self, state: AgentState) -> Dict[str, Any]:
        """Execute the data collection agent.

        Args:
            state: Current agent state

        Returns:
            Partial state with collected data
        """
        symbols = state.get("symbols", [])
        if not symbols:
            logger.warning("No symbols provided for data collection")
            return {"market_data": {}, "financial_data": {}, "news_data": []}

        logger.info(f"Collecting data for {len(symbols)} symbols: {symbols}")

        # Collect data concurrently for all symbols
        tasks = [
            self._collect_symbol_data(symbol)
            for symbol in symbols
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        market_data = {}
        financial_data = {}
        news_data = []

        for symbol, result in zip(symbols, results):
            if isinstance(result, Exception):
                logger.error(f"Failed to collect data for {symbol}: {result}")
                continue

            if result:
                market_data[symbol] = result.get("market_data", {})
                financial_data[symbol] = result.get("financial_data", {})
                news_data.extend(result.get("news_data", []))

        logger.info(
            f"Collected data for {len(market_data)} symbols, "
            f"{len(news_data)} news items"
        )

        # Return only the partial state (fields we modify)
        return {
            "market_data": market_data,
            "financial_data": financial_data,
            "news_data": news_data[-100:],  # Keep last 100 news items
        }

    async def _collect_symbol_data(self, symbol: str) -> Dict[str, Any]:
        """Collect all data for a single symbol.

        Args:
            symbol: Stock symbol

        Returns:
            Dictionary containing market_data, financial_data, news_data
        """
        try:
            # Collect market data
            market_data = await self._fetch_market_data(symbol)

            # Collect financial data
            financial_data = await self._fetch_financial_data(symbol)

            # Collect news
            news_data = await self._fetch_news(symbol)

            return {
                "market_data": market_data,
                "financial_data": financial_data,
                "news_data": news_data,
            }

        except Exception as e:
            logger.error(f"Error collecting data for {symbol}: {e}")
            raise

    async def _fetch_market_data(self, symbol: str) -> Dict[str, Any]:
        """Fetch market data for a symbol.

        Args:
            symbol: Stock symbol

        Returns:
            Dictionary containing price data and statistics
        """
        try:
            # Convert to Yahoo Finance format for Chinese stocks
            yahoo_symbol = convert_to_yahoo_symbol(symbol)
            logger.info(f"Fetching market data for {symbol} (Yahoo: {yahoo_symbol})")

            ticker = yf.Ticker(yahoo_symbol)

            # Get current info
            info = ticker.info

            # Get historical data (last 3 months)
            end_date = datetime.now()
            start_date = end_date - timedelta(days=90)

            hist = ticker.history(start=start_date, end=end_date)

            if hist.empty:
                logger.warning(f"No historical data found for {symbol} (Yahoo: {yahoo_symbol})")
                return {}

            # Convert to dict
            hist_data = self._historical_data_to_dict(hist)

            return {
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
                "description": info.get("longBusinessSummary"),
                "historical_data": hist_data,
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Error fetching market data for {symbol}: {e}")
            return {}

    async def _fetch_financial_data(self, symbol: str) -> Dict[str, Any]:
        """Fetch financial data for a symbol.

        Args:
            symbol: Stock symbol

        Returns:
            Dictionary containing financial metrics
        """
        try:
            yahoo_symbol = convert_to_yahoo_symbol(symbol)
            ticker = yf.Ticker(yahoo_symbol)

            # Get financial statements
            income_stmt = ticker.income_stmt
            balance_sheet = ticker.balance_sheet
            cash_flow = ticker.cashflow

            # Get info
            info = ticker.info

            return {
                "symbol": symbol,
                "metrics": {
                    # Profitability
                    "roe": info.get("returnOnEquity"),
                    "roa": info.get("returnOnAssets"),
                    "profit_margin": info.get("profitMargins"),
                    "operating_margin": info.get("operatingMargins"),
                    # Valuation
                    "pe_ratio": info.get("trailingPE"),
                    "forward_pe": info.get("forwardPE"),
                    "pb_ratio": info.get("priceToBook"),
                    "ps_ratio": info.get("priceToSalesTrailing12Months"),
                    "peg_ratio": info.get("pegRatio"),
                    "enterprise_value": info.get("enterpriseValue"),
                    "ev_ebitda": info.get("enterpriseToEbitda"),
                    # Financial health
                    "debt_to_equity": info.get("debtToEquity"),
                    "current_ratio": info.get("currentRatio"),
                    "quick_ratio": info.get("quickRatio"),
                    "total_cash": info.get("totalCash"),
                    "total_debt": info.get("totalDebt"),
                    "total_revenue": info.get("totalRevenue"),
                    "revenue_per_share": info.get("revenuePerShare"),
                    # Dividends
                    "dividend_yield": info.get("dividendYield"),
                    "dividend_rate": info.get("dividendRate"),
                    "payout_ratio": info.get("payoutRatio"),
                },
                "income_statement": (
                    self._financial_statement_to_dict(income_stmt)
                    if income_stmt is not None
                    else {}
                ),
                "balance_sheet": (
                    self._financial_statement_to_dict(balance_sheet)
                    if balance_sheet is not None
                    else {}
                ),
                "cash_flow": (
                    self._financial_statement_to_dict(cash_flow)
                    if cash_flow is not None
                    else {}
                ),
                "earnings_dates": (
                    ticker.earnings_dates.to_dict("records")
                    if ticker.earnings_dates is not None
                    else []
                ),
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Error fetching financial data for {symbol}: {e}")
            return {}

    async def _fetch_news(self, symbol: str) -> List[Dict[str, Any]]:
        """Fetch news for a symbol.

        Args:
            symbol: Stock symbol

        Returns:
            List of news articles
        """
        try:
            yahoo_symbol = convert_to_yahoo_symbol(symbol)
            ticker = yf.Ticker(yahoo_symbol)
            news = ticker.news

            if not news:
                logger.debug(f"No news found for {symbol} (Yahoo: {yahoo_symbol})")
                return []

            articles = []
            for item in news[:20]:  # Limit to 20 most recent
                # Handle new Yahoo Finance news structure (nested content object)
                content = item.get("content", {})

                # Extract fields from new structure
                title = content.get("title") or item.get("title")
                summary = content.get("summary") or item.get("summary")
                link = None
                if content.get("canonicalUrl"):
                    link = content["canonicalUrl"].get("url")
                if not link and item.get("link"):
                    link = item.get("link")

                # Publisher/source
                provider = content.get("provider", {})
                source = provider.get("displayName") or item.get("publisher")

                # Published date
                published = content.get("pubDate") or item.get("providerPublishTime")

                # Related tickers - ensure original symbol is included
                related = item.get("relatedTickers", [])
                if symbol not in related:
                    related.append(symbol)
                if yahoo_symbol not in related:
                    related.append(yahoo_symbol)

                article = {
                    "title": title,
                    "link": link,
                    "published": published,
                    "source": source,
                    "summary": summary,
                    "related_symbols": related,
                    "original_symbol": symbol,
                }

                # Only include if we have at least a title
                if title:
                    articles.append(article)

            logger.info(f"Fetched {len(articles)} news articles for {symbol}")
            return articles

        except Exception as e:
            logger.error(f"Error fetching news for {symbol}: {e}")
            return []

    def _historical_data_to_dict(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Convert historical price DataFrame to dictionary.

        Args:
            df: Historical price DataFrame

        Returns:
            Dictionary with price data
        """
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

    def _financial_statement_to_dict(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Convert financial statement DataFrame to dictionary.

        Args:
            df: Financial statement DataFrame

        Returns:
            Dictionary with financial data
        """
        if df is None or df.empty:
            return {}

        return {
            "dates": [d.strftime("%Y-%m-%d") for d in df.columns],
            "data": {row: df.loc[row].tolist() for row in df.index},
        }


class AkShareDataAgent(BaseAgent):
    """Agent for collecting Chinese stock data using AkShare.

    This is an alternative data source for Chinese A-shares.
    AkShare provides comprehensive Chinese market data for free.
    """

    async def execute(self, state: AgentState) -> Dict[str, Any]:
        """Execute the AkShare data collection agent.

        Args:
            state: Current agent state

        Returns:
            Partial state with collected data
        """
        symbols = state.get("symbols", [])

        # Filter for Chinese symbols (6 digits)
        cn_symbols = [s for s in symbols if s.isdigit() and len(s) == 6]

        if not cn_symbols:
            logger.info("No Chinese symbols found, skipping AkShare collection")
            return {"market_data": {}, "financial_data": {}}

        logger.info(f"Collecting Chinese stock data for {len(cn_symbols)} symbols")

        try:
            import akshare as ak

            market_data = {}
            financial_data = {}

            for symbol in cn_symbols:
                # Fetch stock info
                stock_info = await self._fetch_akshare_stock_info(symbol, ak)
                if stock_info:
                    market_data[symbol] = stock_info

                # Fetch financial data
                stock_financials = await self._fetch_akshare_financials(symbol, ak)
                if stock_financials:
                    financial_data[symbol] = stock_financials

            logger.info(f"Collected AkShare data for {len(market_data)} symbols")

            # Return only the partial state (fields we modify)
            return {
                "market_data": market_data,
                "financial_data": financial_data,
            }

        except ImportError:
            logger.warning("AkShare not installed, skipping Chinese stock data")
            return {"market_data": {}, "financial_data": {}}
        except Exception as e:
            logger.error(f"Error collecting AkShare data: {e}")
            return {"market_data": {}, "financial_data": {}}

    async def _fetch_akshare_stock_info(
        self, symbol: str, ak
    ) -> Optional[Dict[str, Any]]:
        """Fetch Chinese stock info using AkShare.

        Args:
            symbol: Stock symbol (6 digits)
            ak: AkShare module

        Returns:
            Dictionary containing stock data
        """
        try:
            # Determine market (SH or SZ)
            exchange = "sh" if symbol.startswith("6") else "sz"
            stock_code = f"{symbol}.{exchange.upper()}"

            # Get real-time quote
            df = ak.stock_zh_a_spot_em()

            stock_row = df[df["代码"] == symbol]

            if stock_row.empty:
                return None

            row = stock_row.iloc[0]

            return {
                "symbol": symbol,
                "current_price": row.get("最新价"),
                "change": row.get("涨跌幅", 0),
                "change_percent": row.get("涨跌幅", 0),
                "volume": row.get("成交量"),
                "amount": row.get("成交额"),
                "amplitude": row.get("振幅"),
                "high": row.get("最高"),
                "low": row.get("最低"),
                "open": row.get("今开"),
                "previous_close": row.get("昨收"),
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Error fetching AkShare data for {symbol}: {e}")
            return None

    async def _fetch_akshare_financials(
        self, symbol: str, ak
    ) -> Optional[Dict[str, Any]]:
        """Fetch Chinese stock financials using AkShare.

        Args:
            symbol: Stock symbol (6 digits)
            ak: AkShare module

        Returns:
            Dictionary containing financial data
        """
        try:
            # Get main financial indicators
            df = ak.stock_financial_analysis_indicator(symbol=symbol)

            if df.empty:
                return None

            latest = df.iloc[-1]

            return {
                "symbol": symbol,
                "metrics": {
                    "roe": latest.get("净资产收益率"),
                    "roa": latest.get("总资产净利率"),
                    "gross_margin": latest.get("销售毛利率"),
                    "net_margin": latest.get("销售净利率"),
                    "debt_to_asset": latest.get("资产负债率"),
                    "current_ratio": latest.get("流动比率"),
                    "quick_ratio": latest.get("速动比率"),
                },
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Error fetching AkShare financials for {symbol}: {e}")
            return None
