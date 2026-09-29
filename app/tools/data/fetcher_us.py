"""US/international history sources: Sina daily bars, the direct Yahoo
v8 chart API, and Stooq CSV. Split from fetcher.py (behavior-preserving);
outside callers keep importing from fetcher.py."""

import asyncio
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import requests

from app.tools.data.fetcher_common import (
    DEFAULT_HISTORY_DAYS,
    DEFAULT_HISTORY_PERIOD,
    _convert_to_yahoo_symbol,
    _period_to_days,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)


async def _sina_us_hist(symbol: str, period: str = DEFAULT_HISTORY_PERIOD) -> dict[str, Any] | None:
    """US daily bars via Sina (``ak.stock_us_daily``).

    The only US history source that answers from the Tencent Cloud deploy
    when Yahoo rate-limits — verified live in the production container
    2026-09-25: East Money's US kline/list endpoints are connection-dropped
    from that host, while Sina serves the full adjusted daily history for a
    plain ticker (no market-prefix code mapping needed). Sina takes no date
    arguments, so the requested period window is sliced locally.
    """

    def _fetch():
        import akshare as ak

        df = ak.stock_us_daily(symbol=symbol, adjust="qfq")
        if df is None or df.empty:
            return None
        dates = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        cutoff = (datetime.now() - timedelta(days=_period_to_days(period))).strftime("%Y-%m-%d")
        window = dates >= cutoff
        return {
            "dates": dates[window].tolist(),
            "open": df["open"][window].tolist(),
            "high": df["high"][window].tolist(),
            "low": df["low"][window].tolist(),
            "close": df["close"][window].tolist(),
            "volume": df["volume"][window].tolist() if "volume" in df else [],
        }

    try:
        result = await asyncio.to_thread(_fetch)
    except Exception as e:
        logger.warning(f"[sina-us-hist] failed for {symbol}: {e}")
        return None
    if result and result.get("dates"):
        return result
    return None


# ── Provider 3: Direct Yahoo Finance API ─────────────────────────


_YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
}


async def _yahoo_api_fetch(symbol: str) -> dict[str, Any] | None:
    """Fetch via direct Yahoo Finance v8 API."""
    yahoo_symbol = _convert_to_yahoo_symbol(symbol)

    try:
        # Get quote
        def _get_quote():
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}"
            params = {
                "range": DEFAULT_HISTORY_PERIOD,
                "interval": "1d",
                "includePrePost": "false",
            }
            r = requests.get(url, params=params, headers=_YAHOO_HEADERS, timeout=15)
            r.raise_for_status()
            return r.json()

        data = await asyncio.to_thread(_get_quote)
        result = data.get("chart", {}).get("result", [])
        if not result:
            return None

        meta = result[0].get("meta", {})
        quotes = result[0].get("indicators", {}).get("quote", [{}])[0]
        timestamps = result[0].get("timestamp", [])

        current = meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")

        hist_dates = []
        if timestamps:
            hist_dates = [datetime.fromtimestamp(t).strftime("%Y-%m-%d") for t in timestamps]

        market_data = {
            "symbol": symbol,
            "yahoo_symbol": yahoo_symbol,
            "current_price": current,
            "previous_close": prev,
            "change": current - prev if current and prev else None,
            "change_percent": ((current - prev) / prev * 100) if current and prev else None,
            "volume": meta.get("regularMarketVolume"),
            "market_cap": meta.get("marketCap"),
            "52_week_high": None,
            "52_week_low": None,
            "company_name": meta.get("shortName"),
            "currency": meta.get("currency"),
            "historical_data": {
                "dates": hist_dates,
                "open": quotes.get("open", []),
                "high": quotes.get("high", []),
                "low": quotes.get("low", []),
                "close": quotes.get("close", []),
                "volume": quotes.get("volume", []),
            },
        }

        if current:
            logger.info(f"[yahoo-api] OK for {symbol}")
            return {"market_data": market_data, "financial_data": {"metrics": {}}, "news_data": []}

    except Exception as e:
        logger.warning(f"[yahoo-api] failed for {symbol}: {e}")

    return None


async def _stooq_fetch(symbol: str) -> dict[str, Any] | None:
    """Fetch via Stooq.com free CSV download."""
    try:
        stooq_symbol = symbol.lower().replace(".", "-")
        start_date = (datetime.now() - timedelta(days=DEFAULT_HISTORY_DAYS)).strftime("%Y%m%d")
        end_date = datetime.now().strftime("%Y%m%d")
        url = f"https://stooq.com/q/d/l/?s={stooq_symbol}" f"&d1={start_date}&d2={end_date}&i=d"

        def _get():
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            from io import StringIO

            df = pd.read_csv(StringIO(r.text))
            return df

        df = await asyncio.to_thread(_get)
        if df is None or df.empty:
            return None

        closes = df["Close"].tolist()
        current = closes[-1] if closes else None
        prev = closes[-2] if len(closes) > 1 else None

        market_data = {
            "symbol": symbol,
            "current_price": current,
            "previous_close": prev,
            "change": current - prev if current and prev else None,
            "change_percent": ((current - prev) / prev * 100) if current and prev else None,
            "historical_data": {
                "dates": df["Date"].tolist() if "Date" in df else [],
                "open": df["Open"].tolist() if "Open" in df else [],
                "high": df["High"].tolist() if "High" in df else [],
                "low": df["Low"].tolist() if "Low" in df else [],
                "close": closes,
                "volume": df["Volume"].tolist() if "Volume" in df else [],
            },
        }

        if current:
            logger.info(f"[stooq] OK for {symbol}")
            return {"market_data": market_data, "financial_data": {"metrics": {}}, "news_data": []}

    except Exception as e:
        logger.warning(f"[stooq] failed for {symbol}: {e}")

    return None
