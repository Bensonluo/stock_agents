"""Cache, symbol mappers, and snapshot-shape helpers shared by every
fetcher_* provider module. Split from fetcher.py (behavior-preserving);
the canonical import surface for outside callers remains fetcher.py."""

import time
from datetime import datetime
from typing import Any

import pandas as pd

# Simple in-memory cache: key -> (data, timestamp)
_cache: dict[str, tuple[Any, float]] = {}
_CACHE_TTL = 1800  # 30 minutes - long enough to survive across tool calls in one analysis
DEFAULT_HISTORY_PERIOD = "3y"
DEFAULT_HISTORY_DAYS = 3 * 365


def _percentage_to_ratio(value: Any) -> float | None:
    """Convert provider percentage values (75 means 75%) to decimal ratios."""
    if value is None:
        return None
    return float(value) / 100.0


def _period_to_days(period: str) -> int:
    return {
        "1mo": 30,
        "3mo": 90,
        "6mo": 180,
        "1y": 365,
        "2y": 730,
        "3y": DEFAULT_HISTORY_DAYS,
        "5y": 5 * 365,
    }.get(period, DEFAULT_HISTORY_DAYS)


def _history_covers_period(result: dict[str, Any], period: str, min_fraction: float = 0.5) -> bool:
    """True when the returned date span covers a fair share of the request.

    Alpha Vantage's free tier caps TIME_SERIES_DAILY at the most recent 100
    entries; without this gate that thin slice "succeeds" and terminates the
    chain before the multi-year sources further down (AkShare for CN, Sina
    for US) ever run — ``fetch_historical(period="3y")`` silently returned
    100 bars (first empirical walk-forward run, 2026-09-25). The gate is
    applied to capped providers only: a full-history source whose short
    result reflects genuinely short history stays acceptable.
    """
    dates = result.get("dates") or []
    if len(dates) < 2:
        return False
    try:
        first = datetime.strptime(str(dates[0])[:10], "%Y-%m-%d")
        last = datetime.strptime(str(dates[-1])[:10], "%Y-%m-%d")
    except ValueError:
        return False
    span_days = (last - first).days + 1
    return span_days >= min_fraction * _period_to_days(period)


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
    if _is_hk_symbol(symbol):
        return f"{_hk_code(symbol)}.HK"
    if symbol.isdigit() and len(symbol) == 6:
        if symbol.startswith("6"):
            return f"{symbol}.SS"
        elif symbol.startswith("0") or symbol.startswith("3"):
            return f"{symbol}.SZ"
        return f"{symbol}.SS"
    return symbol


def _is_chinese_symbol(symbol: str) -> bool:
    return symbol.isdigit() and len(symbol) == 6


def _cn_tencent_symbol(symbol: str) -> str:
    """6-digit A-share code -> Tencent market-prefixed code (sh600000/sz000001).

    Same SH/SZ split as `_convert_to_yahoo_symbol` (6 -> Shanghai, 0/3 ->
    Shenzhen, anything else defaults to Shanghai).
    """
    if symbol.startswith(("0", "3")):
        return f"sz{symbol}"
    return f"sh{symbol}"


def _is_hk_symbol(symbol: str) -> bool:
    """HK-listed codes: '0700.HK'/'00700.HK' suffixed, or bare 4-5 digit
    zero-padded codes ('0700', '00700')."""
    upper = symbol.upper()
    if upper.endswith(".HK"):
        digits = upper[:-3]
        return digits.isdigit() and 4 <= len(digits) <= 5
    return symbol.isdigit() and symbol[0] == "0" and len(symbol) in (4, 5)


def _hk_code(symbol: str) -> str:
    """Normalize to the 4-digit Yahoo form ('00700'/'0700.HK' -> '0700')."""
    digits = symbol.upper().removesuffix(".HK").lstrip("0") or "0"
    return digits.zfill(4)


def _hk_akshare_code(symbol: str) -> str:
    """akshare HK endpoints use the 5-digit zero-padded form ('00700')."""
    return _hk_code(symbol).zfill(5)


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


def _snapshot_has_price(result: dict[str, Any]) -> bool:
    """Accept flat {'market_data': {'current_price': ...}} (yfinance/finnhub)
    and symbol-keyed {'market_data': {'0700.HK': {'current_price': ...}}}
    (tencent/eastmoney/alphavantage/akshare) provider shapes."""
    market = result.get("market_data") or {}
    if not isinstance(market, dict):
        return False
    if market.get("current_price"):
        return True
    for value in market.values():
        if isinstance(value, dict) and value.get("current_price"):
            return True
    return False


def _flatten_snapshot(result: dict[str, Any], symbol: str) -> dict[str, Any]:
    """Normalize symbol-keyed provider results to the flat snapshot shape
    ({'market_data': {...flat...}, 'financial_data': ..., 'news_data': ...})
    that get_stock_overview / _fetch_and_split expect — the same shape the
    yfinance provider has always returned."""
    market = result.get("market_data") or {}
    if isinstance(market, dict) and not market.get("current_price"):
        for value in market.values():
            if isinstance(value, dict) and value.get("current_price"):
                return {
                    "market_data": {**value, "symbol": symbol},
                    "financial_data": result.get("financial_data") or {},
                    "news_data": result.get("news_data") or [],
                }
    return result
