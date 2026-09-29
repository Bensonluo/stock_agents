"""Multi-source stock data fetcher with automatic fallback.

Provider chain: yfinance -> finnhub -> akshare -> direct Yahoo Finance API -> stooq

Split (behavior-preserving) into sibling modules — fetcher_common (cache and
symbol helpers), fetcher_us, fetcher_benchmarks, fetcher_news,
fetcher_yfinance, fetcher_hk, fetcher_cn, fetcher_finnhub — which this
module re-exports in full so existing import sites and test seams keep
working. Kept here: the orchestrators (fetch_stock_data with the provider
registration tuples, fetch_historical), the akshare dispatch, and the Alpha
Vantage block whose cooldown state is module-global.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import requests

from app.config import get_settings
from app.tools.data.fetcher_benchmarks import (  # noqa: F401
    _SECTOR_ETF_TICKERS,  # noqa: F401
    BENCHMARK_HISTORY_PERIOD,  # noqa: F401
    BENCHMARK_TICKERS,  # noqa: F401
    SECTOR_BENCHMARK_ETFS,  # noqa: F401
    _sync_cn_industry_history,  # noqa: F401
    _sync_cn_industry_name,  # noqa: F401
    _sync_fetch_benchmark_history,  # noqa: F401
    benchmark_ticker_for,  # noqa: F401
    fetch_benchmark_history,  # noqa: F401
    fetch_cn_sector_benchmark,  # noqa: F401
    sector_benchmark_ticker,  # noqa: F401
    tencent_index_history,  # noqa: F401
)
from app.tools.data.fetcher_cn import (  # noqa: F401
    _akshare_cn,  # noqa: F401
    _debt_to_equity_from_asset_ratio,  # noqa: F401
    _indicator_value,  # noqa: F401
    _pct_to_ratio,  # noqa: F401
    _sync_fetch_akshare_financials,  # noqa: F401
    _sync_fetch_tencent_cn_hist,  # noqa: F401
)
from app.tools.data.fetcher_common import (  # noqa: F401
    _CACHE_TTL,  # noqa: F401
    DEFAULT_HISTORY_DAYS,  # noqa: F401
    DEFAULT_HISTORY_PERIOD,  # noqa: F401
    _cache,  # noqa: F401
    _cache_get,  # noqa: F401
    _cache_set,  # noqa: F401
    _cn_tencent_symbol,  # noqa: F401
    _convert_to_yahoo_symbol,  # noqa: F401
    _flatten_snapshot,  # noqa: F401
    _hist_df_to_dict,  # noqa: F401
    _history_covers_period,  # noqa: F401
    _hk_akshare_code,  # noqa: F401
    _hk_code,  # noqa: F401
    _is_chinese_symbol,  # noqa: F401
    _is_hk_symbol,  # noqa: F401
    _percentage_to_ratio,  # noqa: F401
    _period_to_days,  # noqa: F401
    _snapshot_has_price,  # noqa: F401
)
from app.tools.data.fetcher_finnhub import (  # noqa: F401
    _FINNHUB_BASE,  # noqa: F401
    _finnhub_fetch,  # noqa: F401
    _finnhub_get,  # noqa: F401
    _finnhub_historical,  # noqa: F401
    fetch_us_news,  # noqa: F401
)
from app.tools.data.fetcher_hk import (  # noqa: F401
    _EASTMONEY_HEADERS,  # noqa: F401
    _akshare_hk,  # noqa: F401
    _eastmoney_hk_fetch,  # noqa: F401
    _eastmoney_hk_klines,  # noqa: F401
    _eastmoney_klines_to_hist,  # noqa: F401
    _tencent_hk_fetch,  # noqa: F401
    _tencent_hk_klines,  # noqa: F401
    _tencent_hk_quote,  # noqa: F401
)
from app.tools.data.fetcher_news import (  # noqa: F401
    _CN_NEWS_CACHE_TTL,  # noqa: F401
    _EARNINGS_COLUMN_ALIASES,  # noqa: F401
    _earnings_value,  # noqa: F401
    dedup_news,  # noqa: F401
    earnings_records,  # noqa: F401
    fetch_cn_news,  # noqa: F401
    finnhub_news_articles,  # noqa: F401
    yfinance_news_articles,  # noqa: F401
)
from app.tools.data.fetcher_us import (  # noqa: F401
    _YAHOO_HEADERS,  # noqa: F401
    _sina_us_hist,  # noqa: F401
    _stooq_fetch,  # noqa: F401
    _yahoo_api_fetch,  # noqa: F401
)
from app.tools.data.fetcher_yfinance import _yfinance_fetch  # noqa: F401
from app.tools.data.provider_health import record_provider_outcome
from app.utils.logging import get_logger

logger = get_logger(__name__)

# ── Provider 2: akshare ─────────────────────────────────────────


async def _akshare_fetch(symbol: str) -> dict[str, Any] | None:
    """Fetch via akshare."""
    import akshare as ak

    try:
        if _is_chinese_symbol(symbol):
            return await _akshare_cn(symbol, ak)
        if _is_hk_symbol(symbol):
            return await _akshare_hk(symbol, ak)
        return await _akshare_us(symbol, ak)
    except Exception as e:
        logger.warning(f"[akshare] failed for {symbol}: {e}")
        return None


async def _akshare_us(symbol: str, ak: Any) -> dict[str, Any] | None:
    """US stock via akshare (Sina daily history; see ``_sina_us_hist``)."""

    hist = await _sina_us_hist(symbol)
    if hist is None:
        return None

    closes = hist["close"]
    current = closes[-1] if closes else None
    prev = closes[-2] if len(closes) > 1 else None

    market_data = {
        "symbol": symbol,
        "current_price": current,
        "previous_close": prev,
        "change": current - prev if current and prev else None,
        "change_percent": ((current - prev) / prev * 100) if current and prev else None,
        "volume": hist["volume"][-1] if hist.get("volume") else None,
        # Sina quotes US stocks in USD; the report layer's currency-aware
        # formatting keys off this (iteration 55).
        "currency": "USD",
        "historical_data": hist,
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


# ── Provider 2c: Alpha Vantage (25 req/day free, historical OHLC) ────


# Back off for a minute after Alpha Vantage signals a rate limit — the agent's
# retry loops can otherwise burn the free 5 req/min cap in seconds.
_AV_COOLDOWN_UNTIL = 0.0

_ALPHAVANTAGE_BASE = "https://www.alphavantage.co/query"


def _alphavantage_get(params: dict[str, Any]) -> dict[str, Any] | None:
    """Synchronous Alpha Vantage GET. Returns parsed JSON or None on error.

    Free tier: 25 req/day, 1 req/sec burst, 5 req/min sustained.
    Rate-limited responses carry a "Note" or "Information" field — treat as miss
    and cool down so callers fall through to other providers.
    """
    import time

    global _AV_COOLDOWN_UNTIL
    api_key = get_settings().alpha_vantage_key
    if not api_key:
        return None
    if time.monotonic() < _AV_COOLDOWN_UNTIL:
        return None
    qp = {**params, "apikey": api_key}
    try:
        r = requests.get(_ALPHAVANTAGE_BASE, params=qp, timeout=20)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict):
            return None
        if any(k in data for k in ("Note", "Information", "Error Message", "error")):
            logger.warning(
                f"[alphavantage] {data.get('Note') or data.get('Information') or data.get('Error Message') or data.get('error')}"
            )
            _AV_COOLDOWN_UNTIL = time.monotonic() + 60
            return None
        return data
    except Exception as e:
        logger.warning(f"[alphavantage] request failed: {e}")
        return None


async def _alphavantage_historical(symbol: str, period: str) -> dict[str, Any] | None:
    """Historical OHLC via Alpha Vantage TIME_SERIES_DAILY.

    Verified format (alphavantage.co docs + Stack Overflow):
      {
        "Meta Data": {...},
        "Time Series (Daily)": {
          "YYYY-MM-DD": {"1. open", "2. high", "3. low", "4. close", "5. volume"},
          ...
        }
      }

    Free tier constraint (discovered at runtime 2026-06-12):
      - outputsize=full is PREMIUM only
      - outputsize=compact returns last 100 days only
    So we always use compact; for periods > 100 days the user gets < N days.
    """
    if not get_settings().alpha_vantage_key:
        return None

    def _get():
        return _alphavantage_get(
            {
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "outputsize": "compact",  # 100 days; full is premium-only
            }
        )

    data = await asyncio.to_thread(_get)
    if not data:
        return None

    series = data.get("Time Series (Daily)")
    if not isinstance(series, dict) or not series:
        return None

    period_days = _period_to_days(period)
    cutoff = (datetime.now() - timedelta(days=period_days)).strftime("%Y-%m-%d")
    rows = [(d, v) for d, v in series.items() if d >= cutoff]
    rows.sort(key=lambda x: x[0])

    if not rows:
        return None

    dates, opens, highs, lows, closes, volumes = [], [], [], [], [], []
    for d, v in rows:
        try:
            dates.append(d)
            opens.append(float(v["1. open"]))
            highs.append(float(v["2. high"]))
            lows.append(float(v["3. low"]))
            closes.append(float(v["4. close"]))
            volumes.append(int(v["5. volume"]))
        except (KeyError, ValueError):
            continue

    if not dates:
        return None

    logger.info(f"[alphavantage] OK for {symbol} ({len(dates)} days)")
    return {
        "symbol": symbol,
        "period": period,
        "dates": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    }


# ── Provider 3b: Stooq (free CSV) ────────────────────────────────


async def _alphavantage_fetch(symbol: str) -> dict[str, Any] | None:
    """Snapshot via Alpha Vantage GLOBAL_QUOTE (free tier, 25 req/day).

    Quote fields: 01. symbol, 02. open, 03. high, 04. low, 05. price,
    06. volume, 07. latest day, 08. previous close, 09. change.
    """
    data = _alphavantage_get({"function": "GLOBAL_QUOTE", "symbol": symbol})
    quote = (data or {}).get("Global Quote") or {}
    price = quote.get("05. price")
    if not price:
        return None

    yahoo_symbol = _convert_to_yahoo_symbol(symbol)
    current = float(price)
    previous = float(quote["08. previous close"]) if quote.get("08. previous close") else None
    latest_day = (
        str(quote.get("07. latest trading day") or quote.get("07. latest day") or "") or None
    )

    return {
        "market_data": {
            yahoo_symbol: {
                "symbol": symbol,
                "current_price": current,
                "previous_close": previous,
                "change": current - previous if previous else None,
                "change_percent": (
                    float(quote["10. change percent"].rstrip("%"))
                    if quote.get("10. change percent")
                    else None
                ),
                "volume": int(quote["06. volume"]) if quote.get("06. volume") else None,
                "as_of": latest_day,
                "historical_data": {},
            }
        },
        "financial_data": {},
        "news_data": [],
        "provider": "alphavantage",
    }


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
        ("tencent-hk", _tencent_hk_fetch) if _is_hk_symbol(symbol) else None,
        ("eastmoney-hk", _eastmoney_hk_fetch) if _is_hk_symbol(symbol) else None,
        ("alphavantage", _alphavantage_fetch),
        ("finnhub", _finnhub_fetch),
        ("akshare", _akshare_fetch),
        ("yahoo-api", _yahoo_api_fetch),
    ]
    providers = [p for p in providers if p]

    for name, provider in providers:
        try:
            result = await provider(symbol)
            if result and _snapshot_has_price(result):
                flat = _flatten_snapshot(result, symbol)
                _cache_set(cache_key, flat)
                record_provider_outcome(name, "ok")
                return flat
            record_provider_outcome(name, "fail", "no price")
            logger.info(f"[{name}] no price data for {symbol}, trying next provider")
        except Exception as e:
            record_provider_outcome(name, "fail", f"{type(e).__name__}: {e}")
            logger.warning(f"[{name}] exception for {symbol}: {e}")
        # Small delay between providers to avoid rate limiting
        await asyncio.sleep(1)

    logger.error(f"All providers failed for {symbol}")
    return None


async def fetch_historical(symbol: str, period: str = DEFAULT_HISTORY_PERIOD) -> dict[str, Any]:
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
                "symbol": symbol,
                "period": period,
                "dates": [d.strftime("%Y-%m-%d") for d in df.index],
                "open": df["Open"].tolist(),
                "high": df["High"].tolist(),
                "low": df["Low"].tolist(),
                "close": df["Close"].tolist(),
                "volume": df["Volume"].tolist(),
            }
            record_provider_outcome("yfinance-hist", "ok")
            _cache_set(cache_key, result, ttl=60)
            return result
        record_provider_outcome("yfinance-hist", "fail", "empty frame")
    except Exception as e:
        record_provider_outcome("yfinance-hist", "fail", f"{type(e).__name__}: {e}")
        logger.warning(f"[yfinance-hist] failed for {symbol}: {e}")

    # finnhub (snapshot only on free tier — /stock/candle is paid)
    if get_settings().finnhub_api_key:
        try:
            result = await _finnhub_historical(symbol, period)
            if result and result.get("dates"):
                record_provider_outcome("finnhub-hist", "ok")
                _cache_set(cache_key, result, ttl=60)
                return result
            record_provider_outcome("finnhub-hist", "fail", "no dates")
        except Exception as e:
            record_provider_outcome("finnhub-hist", "fail", f"{type(e).__name__}: {e}")
            logger.warning(f"[finnhub-hist] failed for {symbol}: {e}")

    # alpha vantage (free tier: 25 req/day, 1/sec — 1 call per analysis; the
    # response is CAPPED at the most recent ~100 entries, so a "success" that
    # cannot cover the requested window must not terminate the chain)
    if get_settings().alpha_vantage_key:
        try:
            result = await _alphavantage_historical(symbol, period)
            if result and result.get("dates"):
                if _history_covers_period(result, period):
                    record_provider_outcome("alphavantage-hist", "ok")
                    _cache_set(cache_key, result, ttl=60)
                    return result
                record_provider_outcome(
                    "alphavantage-hist",
                    "fail",
                    f"coverage gate: {len(result['dates'])} bars cannot cover {period}",
                )
                logger.info(
                    f"[alphavantage-hist] {symbol}: {len(result['dates'])} bars cannot "
                    f"cover period={period} — continuing down the chain"
                )
            else:
                record_provider_outcome("alphavantage-hist", "fail", "no dates")
        except Exception as e:
            record_provider_outcome("alphavantage-hist", "fail", f"{type(e).__name__}: {e}")
            logger.warning(f"[alphavantage-hist] failed for {symbol}: {e}")

    # HK: Tencent's own quote APIs first (same network as Tencent Cloud),
    # then the direct East Money scrape; both bypass the akshare wrapper
    # that gets connection-dropped from CN servers.
    if _is_hk_symbol(symbol):
        try:
            result = await _tencent_hk_fetch(symbol)
            market = (result or {}).get("market_data", {}).get(_convert_to_yahoo_symbol(symbol), {})
            hist = market.get("historical_data")
            if hist and hist.get("dates"):
                payload = {"symbol": symbol, "period": period, **hist}
                record_provider_outcome("tencent-hk-hist", "ok")
                _cache_set(cache_key, payload, ttl=60)
                return payload
        except Exception as e:
            record_provider_outcome("tencent-hk-hist", "fail", f"{type(e).__name__}: {e}")
            logger.warning(f"[tencent-hk-hist] failed for {symbol}: {e}")

        try:
            end = datetime.now().strftime("%Y%m%d")
            beg = (datetime.now() - timedelta(days=_period_to_days(period))).strftime("%Y%m%d")
            klines = await asyncio.to_thread(
                _eastmoney_hk_klines, _hk_akshare_code(symbol), beg, end
            )
            if klines:
                hist = _eastmoney_klines_to_hist(klines)
                result = {
                    "symbol": symbol,
                    "period": period,
                    **{k: v for k, v in hist.items()},
                }
                record_provider_outcome("eastmoney-hk-hist", "ok")
                _cache_set(cache_key, result, ttl=60)
                return result
        except Exception as e:
            record_provider_outcome("eastmoney-hk-hist", "fail", f"{type(e).__name__}: {e}")
            logger.warning(f"[eastmoney-hk-hist] failed for {symbol}: {e}")

    # akshare
    try:
        import akshare as ak

        days = _period_to_days(period)
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

        df = None
        if _is_chinese_symbol(symbol):
            em_error: str | None = None
            try:

                def hist_fn():
                    return ak.stock_zh_a_hist(
                        symbol=symbol,
                        period="daily",
                        start_date=start_date,
                        end_date=end_date,
                        adjust="qfq",
                    )

                df = await asyncio.to_thread(hist_fn)
            except Exception as e:
                logger.warning(f"[akshare-hist] East Money failed for {symbol}: {e}")
                em_error = f"{type(e).__name__}: {e}"
            if df is None or df.empty:
                record_provider_outcome(
                    "akshare-cn-hist", "fail", em_error or "empty East Money frame"
                )
                # push2his.eastmoney.com is domain-blocked from the
                # production CN host (2026-09-27) while Tencent's kline
                # answers from the same box: same window, same qfq basis,
                # EM-shaped frame. A Tencent failure falls through to the
                # pre-existing chain below unchanged.
                fallback = await asyncio.to_thread(_sync_fetch_tencent_cn_hist, symbol, ak, days)
                if fallback is not None:
                    df = fallback
            else:
                record_provider_outcome("akshare-cn-hist", "ok")

        elif _is_hk_symbol(symbol):
            hk_error: str | None = None
            try:

                def hist_fn():
                    return ak.stock_hk_hist(
                        symbol=_hk_akshare_code(symbol),
                        period="daily",
                        start_date=start_date,
                        end_date=end_date,
                        adjust="qfq",
                    )

                df = await asyncio.to_thread(hist_fn)
            except Exception as e:
                logger.warning(f"[akshare-hist] HK failed for {symbol}: {e}")
                hk_error = f"{type(e).__name__}: {e}"
            if df is None or df.empty:
                record_provider_outcome("akshare-hk-hist", "fail", hk_error or "empty HK frame")
            else:
                record_provider_outcome("akshare-hk-hist", "ok")

        else:
            # US: Sina daily is the CN-server-viable source (verified live
            # 2026-09-25 — East Money's US kline endpoints are connection-
            # dropped from the Tencent Cloud host and also need market-
            # prefixed codes this chain never had).
            sina = await _sina_us_hist(symbol, period)
            if sina and sina.get("dates"):
                result = {"symbol": symbol, "period": period, **sina}
                record_provider_outcome("sina-us-hist", "ok")
                _cache_set(cache_key, result, ttl=60)
                return result
            record_provider_outcome("sina-us-hist", "fail", "no dates")

        if df is not None and not df.empty:
            col_map = {
                "日期": "date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
            }
            df = df.rename(columns=col_map)
            result = {
                "symbol": symbol,
                "period": period,
                "dates": [str(d) for d in df["date"].tolist()],
                "open": df["open"].tolist(),
                "high": df["high"].tolist(),
                "low": df["low"].tolist(),
                "close": df["close"].tolist(),
                "volume": df["volume"].tolist() if "volume" in df else [],
            }
            _cache_set(cache_key, result, ttl=60)
            return result
    except Exception as e:
        logger.warning(f"[akshare-hist] failed for {symbol}: {e}")

    # Direct Yahoo API
    try:

        def _get():
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}"
            r = requests.get(
                url, params={"range": period, "interval": "1d"}, headers=_YAHOO_HEADERS, timeout=15
            )
            r.raise_for_status()
            return r.json()

        data = await asyncio.to_thread(_get)
        result_list = data.get("chart", {}).get("result", [])
        if result_list:
            quotes = result_list[0].get("indicators", {}).get("quote", [{}])[0]
            timestamps = result_list[0].get("timestamp", [])
            dates = (
                [datetime.fromtimestamp(t).strftime("%Y-%m-%d") for t in timestamps]
                if timestamps
                else []
            )
            if dates:
                result = {
                    "symbol": symbol,
                    "period": period,
                    "dates": dates,
                    "open": quotes.get("open", []),
                    "high": quotes.get("high", []),
                    "low": quotes.get("low", []),
                    "close": quotes.get("close", []),
                    "volume": quotes.get("volume", []),
                }
                record_provider_outcome("yahoo-api-hist", "ok")
                _cache_set(cache_key, result, ttl=60)
                return result
        record_provider_outcome("yahoo-api-hist", "fail", "no chart data")
    except Exception as e:
        record_provider_outcome("yahoo-api-hist", "fail", f"{type(e).__name__}: {e}")
        logger.warning(f"[yahoo-api-hist] failed for {symbol}: {e}")

    # Stooq free CSV (last resort; accessible from CN where Yahoo blocks)
    try:
        stooq_base = yahoo_symbol.lower().replace(".", "-")
        # Stooq keys US tickers with a .us suffix (s=aapl.us); dotted
        # international/CN/HK yahoo symbols keep their dashed form.
        stooq_symbol = f"{stooq_base}.us" if "." not in yahoo_symbol else stooq_base
        days = _period_to_days(period)
        d1 = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        d2 = datetime.now().strftime("%Y%m%d")

        def _stooq_hist():
            from io import StringIO

            r = requests.get(
                f"https://stooq.com/q/d/l/?s={stooq_symbol}&d1={d1}&d2={d2}&i=d",
                timeout=15,
            )
            r.raise_for_status()
            return pd.read_csv(StringIO(r.text))

        df = await asyncio.to_thread(_stooq_hist)
        if df is not None and not df.empty and "Close" in df.columns:
            result = {
                "symbol": symbol,
                "period": period,
                "dates": [str(d) for d in df["Date"].tolist()],
                "open": df["Open"].tolist() if "Open" in df else [],
                "high": df["High"].tolist() if "High" in df else [],
                "low": df["Low"].tolist() if "Low" in df else [],
                "close": df["Close"].tolist(),
                "volume": df["Volume"].tolist() if "Volume" in df else [],
            }
            record_provider_outcome("stooq-hist", "ok")
            _cache_set(cache_key, result, ttl=60)
            return result
        record_provider_outcome("stooq-hist", "fail", "no usable frame")
    except Exception as e:
        record_provider_outcome("stooq-hist", "fail", f"{type(e).__name__}: {e}")
        logger.warning(f"[stooq-hist] failed for {symbol}: {e}")

    return {"error": f"All providers failed for {symbol}", "symbol": symbol}
