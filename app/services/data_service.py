"""Data service for fetching stock market data."""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import yfinance as yf

from app.utils.logging import get_logger

logger = get_logger(__name__)


class DataService:
    """Service for fetching stock market data from various sources.

    Supports:
    - yfinance (Yahoo Finance) - primary for US and international stocks
    - AkShare - can be added for Chinese stocks
    """

    def __init__(self):
        """Initialize the data service."""
        self.cache = {}
        self.cache_ttl = 300  # 5 minutes

    async def get_quote(self, symbol: str) -> Dict[str, Any]:
        """Get real-time quote for a symbol.

        Args:
            symbol: Stock symbol

        Returns:
            Quote data dictionary
        """
        # Check cache
        cached = self._get_from_cache(f"quote_{symbol}")
        if cached:
            return cached

        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info

            data = {
                "symbol": symbol,
                "name": info.get("longName"),
                "price": info.get("currentPrice") or info.get("regularMarketPrice"),
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
                "pe_ratio": info.get("trailingPE"),
                "dividend_yield": info.get("dividendYield"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "timestamp": datetime.now().isoformat(),
            }

            # Cache the result
            self._add_to_cache(f"quote_{symbol}", data)

            return data

        except Exception as e:
            logger.error(f"Error fetching quote for {symbol}: {e}")
            raise

    async def get_historical_data(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
    ) -> Dict[str, Any]:
        """Get historical price data.

        Args:
            symbol: Stock symbol
            period: Time period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max)
            interval: Data interval (1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo)

        Returns:
            Historical data dictionary
        """
        cache_key = f"hist_{symbol}_{period}_{interval}"
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached

        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval)

            if df.empty:
                return {"symbol": symbol, "data": [], "timestamp": datetime.now().isoformat()}

            data = {
                "symbol": symbol,
                "period": period,
                "interval": interval,
                "dates": [d.strftime("%Y-%m-%d") for d in df.index],
                "open": df["Open"].tolist(),
                "high": df["High"].tolist(),
                "low": df["Low"].tolist(),
                "close": df["Close"].tolist(),
                "volume": df["Volume"].tolist(),
                "timestamp": datetime.now().isoformat(),
            }

            self._add_to_cache(cache_key, data, ttl=60)  # Shorter cache for historical

            return data

        except Exception as e:
            logger.error(f"Error fetching historical data for {symbol}: {e}")
            raise

    async def get_company_info(self, symbol: str) -> Dict[str, Any]:
        """Get detailed company information.

        Args:
            symbol: Stock symbol

        Returns:
            Company information dictionary
        """
        cache_key = f"info_{symbol}"
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached

        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info

            data = {
                "symbol": symbol,
                "company_name": info.get("longName"),
                "legal_name": info.get("longName"),
                "short_name": info.get("shortName"),
                "website": info.get("website"),
                "industry": info.get("industry"),
                "sector": info.get("sector"),
                "long_business_summary": info.get("longBusinessSummary"),
                "employees": info.get("fullTimeEmployees"),
                "headquarters": {
                    "city": info.get("city"),
                    "state": info.get("state"),
                    "country": info.get("country"),
                    "address": info.get("address1"),
                },
                "market": {
                    "market_cap": info.get("marketCap"),
                    "enterprise_value": info.get("enterpriseValue"),
                    "trailing_pe": info.get("trailingPE"),
                    "forward_pe": info.get("forwardPE"),
                    "peg_ratio": info.get("pegRatio"),
                    "price_to_book": info.get("priceToBook"),
                    "enterprise_to_revenue": info.get("enterpriseToRevenue"),
                    "enterprise_to_ebitda": info.get("enterpriseToEbitda"),
                    "beta": info.get("beta"),
                    "52_week_high": info.get("fiftyTwoWeekHigh"),
                    "52_week_low": info.get("fiftyTwoWeekLow"),
                    "50_day_moving_avg": info.get("fiftyDayAverage"),
                    "200_day_moving_avg": info.get("twoHundredDayAverage"),
                },
                "trading": {
                    "current_price": info.get("currentPrice"),
                    "previous_close": info.get("previousClose"),
                    "day_high": info.get("dayHigh"),
                    "day_low": info.get("dayLow"),
                    "52_week_high": info.get("fiftyTwoWeekHigh"),
                    "52_week_low": info.get("fiftyTwoWeekLow"),
                    "volume": info.get("volume"),
                    "average_volume": info.get("averageVolume"),
                    "average_daily_volume_10day": info.get("averageDailyVolume10Day"),
                },
                "dividends": {
                    "dividend_rate": info.get("dividendRate"),
                    "dividend_yield": info.get("dividendYield"),
                    "payout_ratio": info.get("payoutRatio"),
                    "ex_dividend_date": info.get("exDividendDate"),
                    "last_dividend_date": info.get("lastDividendDate"),
                },
                "timestamp": datetime.now().isoformat(),
            }

            self._add_to_cache(cache_key, data)

            return data

        except Exception as e:
            logger.error(f"Error fetching company info for {symbol}: {e}")
            raise

    async def search_symbols(self, query: str, limit: int = 10) -> List[Dict[str, str]]:
        """Search for stock symbols.

        Args:
            query: Search query
            limit: Maximum number of results

        Returns:
            List of matching symbols
        """
        # This is a simplified search - in production, you'd use a proper search API
        try:
            import requests

            # Use Yahoo Finance search API (unofficial)
            url = f"https://query2.finance.yahoo.com/v1/finance/search"
            params = {
                "q": query,
                "quotesCount": limit,
                "newsCount": 0,
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            results = []
            for quote in data.get("quotes", [])[:limit]:
                if quote.get("quoteType") in ["EQUITY", "ETF", "INDEX"]:
                    results.append({
                        "symbol": quote.get("symbol"),
                        "name": quote.get("longname") or quote.get("shortname"),
                        "exchange": quote.get("exchange"),
                    })

            return results

        except Exception as e:
            logger.error(f"Error searching symbols: {e}")
            return []

    def _get_from_cache(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired.

        Args:
            key: Cache key

        Returns:
            Cached value or None
        """
        if key in self.cache:
            value, timestamp = self.cache[key]
            if (datetime.now() - timestamp).total_seconds() < self.cache_ttl:
                return value
            else:
                # Remove expired entry
                del self.cache[key]
        return None

    def _add_to_cache(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Add value to cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds (uses default if not provided)
        """
        self.cache[key] = (value, datetime.now())

    def clear_cache(self) -> None:
        """Clear all cached data."""
        self.cache.clear()
