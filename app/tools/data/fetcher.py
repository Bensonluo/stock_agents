"""Multi-source stock data fetcher with automatic fallback.

Provider chain: yfinance -> akshare -> direct Yahoo Finance API via requests
"""

import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import requests

from app.utils.logging import get_logger

logger = get_logger(__name__)

# Simple in-memory cache: key -> (data, timestamp)
_cache: dict[str, tuple[Any, float]] = {}
_CACHE_TTL = 1800  # 30 minutes - long enough to survive across tool calls in one analysis


def _cache_get(key: str) -> Any | None:
    if key in _cache:
        data, ts = _cache[key]
        if time.time() - ts < _CACHE_TTL:
            return data
        del _cache[key]
    return None


def _cache_set(key: str, data: Any, ttl: int = _CACHE_TTL) -> None:
    _cache[key] = (data, time.time())
    # Evict old entries if cache grows too large
    if len(_cache) > 200:
        now = time.time()
        expired = [k for k, (_, ts) in _cache.items() if now - ts > ttl]
        for k in expired:
            del _cache[k]


def _convert_to_yahoo_symbol(symbol: str) -> str:
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


def _is_chinese_symbol(symbol: str) -> bool:
    return symbol.isdigit() and len(symbol) == 6


def _hist_df_to_dict(df: pd.DataFrame) -> dict:
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


# ── Provider 1: yfinance (with retry) ────────────────────────────


async def _yfinance_fetch(symbol: str) -> dict[str, Any] | None:
    """Fetch via yfinance with retry."""
    import yfinance as yf

    yahoo_symbol = _convert_to_yahoo_symbol(symbol)

    def _sync():
        ticker = yf.Ticker(yahoo_symbol)
        info = ticker.info
        end_date = datetime.now()
        start_date = end_date - timedelta(days=90)
        hist = ticker.history(start=start_date, end=end_date)
        return info, hist, ticker

    for attempt in range(2):
        try:
            info, hist, ticker = await asyncio.to_thread(_sync)

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
                    "debt_to_equity": info.get("debtToEquity"),
                    "current_ratio": info.get("currentRatio"),
                    "total_revenue": info.get("totalRevenue"),
                    "dividend_yield": info.get("dividendYield"),
                }
            }

            news_data = []
            try:
                for item in (ticker.news or [])[:10]:
                    content = item.get("content", {})
                    title = content.get("title") or item.get("title")
                    if title:
                        news_data.append({
                            "title": title,
                            "summary": content.get("summary") or item.get("summary"),
                            "source": (content.get("provider") or {}).get("displayName") or item.get("publisher"),
                        })
            except Exception:
                pass

            if market_data.get("current_price") or financial_data["metrics"].get("pe_ratio"):
                logger.info(f"[yfinance] OK for {symbol}")
                return {"market_data": market_data, "financial_data": financial_data, "news_data": news_data}

        except Exception as e:
            logger.warning(f"[yfinance] attempt {attempt+1} failed for {symbol}: {e}")
            if attempt < 1:
                await asyncio.sleep(3)

    return None


# ── Provider 2: akshare ─────────────────────────────────────────


async def _akshare_fetch(symbol: str) -> dict[str, Any] | None:
    """Fetch via akshare."""
    import akshare as ak

    try:
        if _is_chinese_symbol(symbol):
            return await _akshare_cn(symbol, ak)
        return await _akshare_us(symbol, ak)
    except Exception as e:
        logger.warning(f"[akshare] failed for {symbol}: {e}")
        return None


async def _akshare_us(symbol: str, ak: Any) -> dict[str, Any] | None:
    """US stock via akshare."""
    # Get historical data
    def _get_hist():
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
        return ak.stock_us_hist(symbol=symbol, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")

    df = await asyncio.to_thread(_get_hist)
    if df is None or df.empty:
        return None

    # Rename columns to English
    col_map = {"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low",
               "成交量": "volume", "涨跌幅": "change_pct"}
    df = df.rename(columns=col_map)

    closes = df["close"].tolist()
    current = closes[-1] if closes else None
    prev = closes[-2] if len(closes) > 1 else None

    market_data = {
        "symbol": symbol,
        "current_price": current,
        "previous_close": prev,
        "change": current - prev if current and prev else None,
        "change_percent": ((current - prev) / prev * 100) if current and prev else None,
        "volume": df["volume"].iloc[-1] if "volume" in df else None,
        "historical_data": {
            "dates": [str(d) for d in df["date"].tolist()],
            "open": df["open"].tolist(),
            "high": df["high"].tolist(),
            "low": df["low"].tolist(),
            "close": closes,
            "volume": df["volume"].tolist() if "volume" in df else [],
        },
    }

    # Try to get valuation data from baidu
    valuation = {}
    try:
        def _get_val():
            return ak.stock_us_valuation_baidu(symbol=symbol, indicator="总市值", period="近一年")
        val_df = await asyncio.to_thread(_get_val)
        if val_df is not None and not val_df.empty:
            latest = val_df.iloc[-1]
            valuation["market_cap"] = latest.iloc[-1] if len(latest) > 1 else None
    except Exception:
        pass

    financial_data = {"metrics": valuation}

    logger.info(f"[akshare] OK for {symbol}")
    return {"market_data": market_data, "financial_data": financial_data, "news_data": []}


async def _akshare_cn(symbol: str, ak: Any) -> dict[str, Any] | None:
    """Chinese A-share via akshare."""
    def _get_hist():
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
        return ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")

    df = await asyncio.to_thread(_get_hist)
    if df is None or df.empty:
        return None

    col_map = {"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low",
               "成交量": "volume", "涨跌幅": "change_pct"}
    df = df.rename(columns=col_map)

    closes = df["close"].tolist()
    current = closes[-1] if closes else None
    prev = closes[-2] if len(closes) > 1 else None

    market_data = {
        "symbol": symbol,
        "current_price": current,
        "previous_close": prev,
        "change": current - prev if current and prev else None,
        "change_percent": ((current - prev) / prev * 100) if current and prev else None,
        "volume": df["volume"].iloc[-1] if "volume" in df else None,
        "historical_data": {
            "dates": [str(d) for d in df["date"].tolist()],
            "open": df["open"].tolist(),
            "high": df["high"].tolist(),
            "low": df["low"].tolist(),
            "close": closes,
            "volume": df["volume"].tolist() if "volume" in df else [],
        },
    }

    logger.info(f"[akshare-CN] OK for {symbol}")
    return {"market_data": market_data, "financial_data": {"metrics": {}}, "news_data": []}


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
            params = {"range": "3mo", "interval": "1d", "includePrePost": "false"}
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


# ── Provider 3b: Stooq (free CSV) ────────────────────────────────


async def _stooq_fetch(symbol: str) -> dict[str, Any] | None:
    """Fetch via Stooq.com free CSV download."""
    try:
        stooq_symbol = symbol.lower().replace(".", "-")
        url = f"https://stooq.com/q/d/l/?s={stooq_symbol}&d1={((datetime.now() - timedelta(days=90)).strftime('%Y%m%d'))}&d2={datetime.now().strftime('%Y%m%d')}&i=d"

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


# ── Unified fetcher ──────────────────────────────────────────────


async def fetch_stock_data(symbol: str) -> dict[str, Any] | None:
    """Fetch stock data with multi-source fallback.

    Tries: yfinance -> akshare -> yahoo-api -> stooq
    Returns the first successful result, or None.
    """
    cache_key = f"stock_{symbol}"
    cached = _cache_get(cache_key)
    if cached:
        logger.info(f"[cache] hit for {symbol}")
        return cached

    providers = [
        ("yfinance", _yfinance_fetch),
        ("akshare", _akshare_fetch),
        ("yahoo-api", _yahoo_api_fetch),
    ]

    for name, provider in providers:
        try:
            result = await provider(symbol)
            if result and result.get("market_data", {}).get("current_price"):
                _cache_set(cache_key, result)
                return result
            logger.info(f"[{name}] no price data for {symbol}, trying next provider")
        except Exception as e:
            logger.warning(f"[{name}] exception for {symbol}: {e}")
        # Small delay between providers to avoid rate limiting
        await asyncio.sleep(1)

    logger.error(f"All providers failed for {symbol}")
    return None


async def fetch_historical(symbol: str, period: str = "3mo") -> dict[str, Any]:
    """Fetch historical prices with fallback."""
    cache_key = f"hist_{symbol}_{period}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    yahoo_symbol = _convert_to_yahoo_symbol(symbol)

    # yfinance
    try:
        import yfinance as yf

        def _sync():
            return yf.Ticker(yahoo_symbol).history(period=period)

        df = await asyncio.to_thread(_sync)
        if not df.empty:
            result = {
                "symbol": symbol, "period": period,
                "dates": [d.strftime("%Y-%m-%d") for d in df.index],
                "open": df["Open"].tolist(), "high": df["High"].tolist(),
                "low": df["Low"].tolist(), "close": df["Close"].tolist(),
                "volume": df["Volume"].tolist(),
            }
            _cache_set(cache_key, result, ttl=60)
            return result
    except Exception as e:
        logger.warning(f"[yfinance-hist] failed for {symbol}: {e}")

    # akshare
    try:
        import akshare as ak

        period_map = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730}
        days = period_map.get(period, 90)
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

        if _is_chinese_symbol(symbol):
            hist_fn = lambda: ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
        else:
            hist_fn = lambda: ak.stock_us_hist(symbol=symbol, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")

        df = await asyncio.to_thread(hist_fn)
        if df is not None and not df.empty:
            col_map = {"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "volume"}
            df = df.rename(columns=col_map)
            result = {
                "symbol": symbol, "period": period,
                "dates": [str(d) for d in df["date"].tolist()],
                "open": df["open"].tolist(), "high": df["high"].tolist(),
                "low": df["low"].tolist(), "close": df["close"].tolist(),
                "volume": df["volume"].tolist() if "volume" in df else [],
            }
            _cache_set(cache_key, result, ttl=60)
            return result
    except Exception as e:
        logger.warning(f"[akshare-hist] failed for {symbol}: {e}")

    # Direct Yahoo API
    try:
        interval_map = {"1d": "1d", "1wk": "1wk", "1mo": "1mo"}
        def _get():
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}"
            r = requests.get(url, params={"range": period, "interval": "1d"}, headers=_YAHOO_HEADERS, timeout=15)
            r.raise_for_status()
            return r.json()

        data = await asyncio.to_thread(_get)
        result_list = data.get("chart", {}).get("result", [])
        if result_list:
            quotes = result_list[0].get("indicators", {}).get("quote", [{}])[0]
            timestamps = result_list[0].get("timestamp", [])
            dates = [datetime.fromtimestamp(t).strftime("%Y-%m-%d") for t in timestamps] if timestamps else []
            if dates:
                result = {
                    "symbol": symbol, "period": period, "dates": dates,
                    "open": quotes.get("open", []), "high": quotes.get("high", []),
                    "low": quotes.get("low", []), "close": quotes.get("close", []),
                    "volume": quotes.get("volume", []),
                }
                _cache_set(cache_key, result, ttl=60)
                return result
    except Exception as e:
        logger.warning(f"[yahoo-api-hist] failed for {symbol}: {e}")

    return {"error": f"All providers failed for {symbol}", "symbol": symbol}
