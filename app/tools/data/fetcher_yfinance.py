"""The yfinance snapshot provider. Split from fetcher.py
(behavior-preserving); outside callers keep importing from fetcher.py."""

import asyncio
from datetime import datetime, timedelta
from typing import Any

from app.tools.data.fetcher_common import (
    DEFAULT_HISTORY_DAYS,
    _convert_to_yahoo_symbol,
    _hist_df_to_dict,
    _percentage_to_ratio,
)
from app.tools.data.fetcher_news import earnings_records, yfinance_news_articles
from app.utils.logging import get_logger

logger = get_logger(__name__)

# ── Provider 1: yfinance (with retry) ────────────────────────────


async def _yfinance_fetch(symbol: str) -> dict[str, Any] | None:
    """Fetch via yfinance with retry."""
    import yfinance as yf

    yahoo_symbol = _convert_to_yahoo_symbol(symbol)

    def _sync():
        ticker = yf.Ticker(yahoo_symbol)
        info = ticker.info
        end_date = datetime.now()
        start_date = end_date - timedelta(days=DEFAULT_HISTORY_DAYS)
        hist = ticker.history(start=start_date, end=end_date)
        try:
            earnings = ticker.earnings_dates
        except Exception:  # annotation-only data must never sink the provider
            earnings = None
        return info, hist, ticker, earnings

    for attempt in range(2):
        try:
            info, hist, ticker, earnings = await asyncio.to_thread(_sync)

            market_data = {}
            if not hist.empty:
                current = info.get("currentPrice") or info.get("regularMarketPrice")
                prev = info.get("previousClose")
                market_data = {
                    "symbol": symbol,
                    "yahoo_symbol": yahoo_symbol,
                    "current_price": current,
                    "previous_close": prev,
                    "change": current - prev if current and prev else None,
                    "change_percent": ((current - prev) / prev * 100) if current and prev else None,
                    "volume": info.get("volume"),
                    "avg_volume": info.get("averageVolume"),
                    "market_cap": info.get("marketCap"),
                    "52_week_high": info.get("fiftyTwoWeekHigh"),
                    "52_week_low": info.get("fiftyTwoWeekLow"),
                    "company_name": info.get("longName"),
                    "sector": info.get("sector"),
                    "industry": info.get("industry"),
                    "currency": info.get("currency"),
                    "historical_data": _hist_df_to_dict(hist),
                }

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
                    "debt_to_equity": _percentage_to_ratio(info.get("debtToEquity")),
                    "current_ratio": info.get("currentRatio"),
                    "quick_ratio": info.get("quickRatio"),
                    "total_revenue": info.get("totalRevenue"),
                    "dividend_yield": info.get("dividendYield"),
                    "revenue_growth": info.get("revenueGrowth"),
                    "earnings_growth": info.get("earningsGrowth"),
                }
            }
            financial_data["metric_units"] = {
                "roe": "ratio",
                "roa": "ratio",
                "profit_margin": "ratio",
                "operating_margin": "ratio",
                "debt_to_equity": "ratio",
                "dividend_yield": "ratio",
                "revenue_growth": "ratio",
                "earnings_growth": "ratio",
            }
            # Event calendar: date-surviving records (see earnings_records)
            # so the report can disclose the next earnings window.
            financial_data["earnings_dates"] = earnings_records(earnings)

            news_data = []
            try:
                news_data = yfinance_news_articles((ticker.news or [])[:10], symbol)
            except Exception:
                pass

            if market_data.get("current_price") or financial_data["metrics"].get("pe_ratio"):
                logger.info(f"[yfinance] OK for {symbol}")
                return {
                    "market_data": market_data,
                    "financial_data": financial_data,
                    "news_data": news_data,
                }

        except Exception as e:
            logger.warning(f"[yfinance] attempt {attempt+1} failed for {symbol}: {e}")
            if attempt < 1:
                await asyncio.sleep(3)

    return None
