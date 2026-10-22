"""The Finnhub provider: snapshot, US news, and the (paid-tier)
historical candle seam. Split from fetcher.py (behavior-preserving);
outside callers keep importing from fetcher.py."""

import asyncio
import time
from datetime import datetime, timedelta
from typing import Any

import requests

from app.config import get_settings
from app.tools.data.fetcher_common import _percentage_to_ratio, _period_to_days
from app.tools.data.fetcher_news import finnhub_news_articles
from app.tools.data.provider_health import record_provider_outcome
from app.utils.logging import get_logger

logger = get_logger(__name__)

# ── Provider 2b: Finnhub (60 req/min free, US stocks) ───────────


_FINNHUB_BASE = "https://finnhub.io/api/v1"


def _finnhub_get(path: str, params: dict[str, Any]) -> dict[str, Any] | list | None:
    """Synchronous Finnhub GET. Returns parsed JSON or None on error."""
    api_key = get_settings().finnhub_api_key
    if not api_key:
        return None
    qp = {**params, "token": api_key}
    try:
        r = requests.get(f"{_FINNHUB_BASE}{path}", params=qp, timeout=15)
        if r.status_code == 429:
            logger.warning(f"[finnhub] rate limited on {path}")
            return None
        r.raise_for_status()
        data = r.json()
        # Finnhub returns {} for some endpoints on free tier — treat as miss
        if isinstance(data, dict) and not data:
            return None
        return data
    except Exception as e:
        logger.warning(f"[finnhub] {path} failed: {e}")
        return None


async def _finnhub_fetch(symbol: str) -> dict[str, Any] | None:
    """Fetch via Finnhub. 4 calls per symbol; well within 60 req/min free tier.

    Note: Finnhub /stock/candle (historical OHLC) is PAID ONLY on the free tier.
    Snapshot, profile, basic metrics, and news are free. We return an empty
    historical_data block; the technical agent can still derive day-level info
    from the quote's o/h/l/pc fields.
    """
    if not get_settings().finnhub_api_key:
        return None

    def _snapshot():
        quote = _finnhub_get("/quote", {"symbol": symbol}) or {}
        profile = _finnhub_get("/stock/profile2", {"symbol": symbol}) or {}
        metric = (_finnhub_get("/stock/metric", {"symbol": symbol, "metric": "all"}) or {}).get(
            "metric", {}
        )
        return quote, profile, metric

    def _news():
        today = datetime.now()
        week_ago = today - timedelta(days=7)
        return (
            _finnhub_get(
                "/company-news",
                {
                    "symbol": symbol,
                    "from": week_ago.strftime("%Y-%m-%d"),
                    "to": today.strftime("%Y-%m-%d"),
                },
            )
            or []
        )

    (snapshot, news) = await asyncio.gather(
        asyncio.to_thread(_snapshot),
        asyncio.to_thread(_news),
    )

    if not isinstance(snapshot, tuple) or len(snapshot) != 3:
        return None
    quote, profile, metric = snapshot

    current = quote.get("c") if isinstance(quote, dict) else None
    if not current:
        logger.info(f"[finnhub] no current price for {symbol}")
        return None

    # marketCapitalization is in millions of currency units
    market_cap = None
    if profile.get("marketCapitalization"):
        market_cap = profile["marketCapitalization"] * 1_000_000

    market_data = {
        "symbol": symbol,
        "current_price": current,
        "previous_close": quote.get("pc"),
        "change": quote.get("d"),
        "change_percent": quote.get("dp"),
        "day_high": quote.get("h"),
        "day_low": quote.get("l"),
        "day_open": quote.get("o"),
        "volume": None,  # /quote doesn't return volume; would need /stock/candle (paid)
        "market_cap": market_cap,
        "52_week_high": metric.get("52WeekHigh"),
        "52_week_low": metric.get("52WeekLow"),
        "company_name": profile.get("name"),
        "sector": profile.get("finnhubIndustry"),
        "currency": profile.get("currency"),
        "exchange": profile.get("exchange"),
        "historical_data": {},  # /stock/candle is paid only on free tier
    }

    financial_data = {
        "metrics": {
            "beta": metric.get("beta"),
            "pe_ratio": metric.get("peBasicExtraTTM"),
            "roe": _percentage_to_ratio(metric.get("roeTTM")),
            "roa": _percentage_to_ratio(metric.get("roaTTM")),
            "dividend_yield": _percentage_to_ratio(metric.get("dividendYieldIndicatedAnnual")),
            "10d_avg_volume": metric.get("10DayAverageTradingVolume"),
            "52_week_high": metric.get("52WeekHigh"),
            "52_week_low": metric.get("52WeekLow"),
        },
        "metric_units": {
            "roe": "ratio",
            "roa": "ratio",
            "dividend_yield": "ratio",
        },
    }

    news_data = finnhub_news_articles(news[:10], symbol=symbol) if isinstance(news, list) else []

    logger.info(f"[finnhub] OK for {symbol}")
    return {"market_data": market_data, "financial_data": financial_data, "news_data": news_data}


async def fetch_us_news(symbol: str) -> list[dict[str, Any]]:
    """US/international news via the provider chain (Finnhub today).

    The pipeline's news path is yfinance-only; when Yahoo rate-limits (the
    documented state of the Tencent Cloud deploy since 2026-09-25), US
    symbols run with an empty sentiment feed. Mirrors ``fetch_cn_news``:
    that seam covers 6-digit codes, this one covers everything else. No
    key configured → ``[]`` — the caller keeps its empty-feed behavior.
    """
    if not get_settings().finnhub_api_key:
        return []

    def _news():
        today = datetime.now()
        week_ago = today - timedelta(days=7)
        return (
            _finnhub_get(
                "/company-news",
                {
                    "symbol": symbol,
                    "from": week_ago.strftime("%Y-%m-%d"),
                    "to": today.strftime("%Y-%m-%d"),
                },
            )
            or []
        )

    try:
        news = await asyncio.to_thread(_news)
    except Exception as e:
        logger.warning(f"[finnhub-news] failed for {symbol}: {e}")
        record_provider_outcome("finnhub-news", "fail", f"{type(e).__name__}: {e}")
        return []
    items = news if isinstance(news, list) else []
    articles = finnhub_news_articles(items[:20], symbol=symbol)
    # Provider-health recording: this seam was the chain's one invisible
    # member -- exceptions are swallowed here and the caller cannot tell
    # key-absent from dark, so the outcome records at the fetcher itself.
    # No key (early return above) stays unrecorded, matching the keyed
    # historical layers' config-off semantics.
    if articles:
        record_provider_outcome("finnhub-news", "ok", f"{len(articles)} articles")
    else:
        record_provider_outcome("finnhub-news", "fail", "feed returned nothing")
    return articles


async def _finnhub_historical(symbol: str, period: str) -> dict[str, Any] | None:
    """Historical OHLC via Finnhub /stock/candle.

    NOTE: /stock/candle is PAID ONLY on the free tier. This function exists for
    when the user upgrades or supplies an alternative. Returns None for free tier.
    """
    if not get_settings().finnhub_api_key:
        return None
    days = _period_to_days(period)
    end_ts = int(time.time())
    start_ts = end_ts - days * 24 * 3600

    def _get():
        return _finnhub_get(
            "/stock/candle",
            {
                "symbol": symbol,
                "resolution": "D",
                "from": start_ts,
                "to": end_ts,
            },
        )

    data = await asyncio.to_thread(_get)
    if not isinstance(data, dict) or data.get("s") != "ok" or not data.get("t"):
        return None
    return {
        "symbol": symbol,
        "period": period,
        "dates": [datetime.fromtimestamp(t).strftime("%Y-%m-%d") for t in data["t"]],
        "open": data.get("o", []),
        "high": data.get("h", []),
        "low": data.get("l", []),
        "close": data.get("c", []),
        "volume": data.get("v", []),
    }
