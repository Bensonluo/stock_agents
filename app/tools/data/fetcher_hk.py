"""The HK chain: Tencent quote APIs, the direct East Money kline
scrape, and the akshare wrapper fallback. Split from fetcher.py
(behavior-preserving); outside callers keep importing from fetcher.py."""

import asyncio
from datetime import datetime, timedelta
from typing import Any

import requests

from app.tools.data.fetcher_common import (
    DEFAULT_HISTORY_DAYS,
    _convert_to_yahoo_symbol,
    _hk_akshare_code,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)


def _tencent_hk_quote(hk_code5: str) -> dict[str, Any] | None:
    """Real-time HK quote via Tencent's own API (qt.gtimg.cn) — native from
    Tencent Cloud servers. Fields (split by ~): name@1, code@2, price@3,
    prev_close@4, open@5, volume@6, ..., high@41 area varies; stable anchors
    below use documented positions for HK rows."""
    r = requests.get(
        f"https://qt.gtimg.cn/q=hk{hk_code5}",
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15,
    )
    r.raise_for_status()
    text = r.content.decode("gbk", errors="replace")
    if '="' not in text:
        return None
    fields = text.split('="', 1)[1].rstrip('";\n').split("~")
    if len(fields) < 50 or not fields[3]:
        return None

    def _f(i: int) -> float | None:
        try:
            return float(fields[i]) if fields[i] else None
        except (ValueError, IndexError):
            return None

    return {
        "name": fields[1],
        "price": _f(3),
        "prev_close": _f(4),
        "open": _f(5),
        "volume": _f(6),
        "high": _f(41) or _f(33),
        "low": _f(42) or _f(34),
        "turnover": _f(37),
    }


def _tencent_hk_klines(hk_code5: str, count: int = 800) -> list[list[str]]:
    """Daily forward-adjusted klines via Tencent ifzq API: rows of
    [date, open, close, high, low, volume, {dividend note?}]."""
    r = requests.get(
        f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=hk{hk_code5},day,,,{count},qfq",
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20,
    )
    r.raise_for_status()
    payload = r.json().get("data") or {}
    day = payload.get(f"hk{hk_code5}") or {}
    return day.get("day") or day.get("qfqday") or []


async def _tencent_hk_fetch(symbol: str) -> dict[str, Any] | None:
    """HK snapshot + history via Tencent's own quote APIs — the primary HK
    route on Tencent Cloud servers (same network as the data source)."""
    code5 = _hk_akshare_code(symbol)

    def _get():
        quote = _tencent_hk_quote(code5)
        klines = _tencent_hk_klines(code5)
        return quote, klines

    quote, klines = await asyncio.to_thread(_get)
    if not klines and not quote:
        return None

    hist: dict[str, list] = {
        "dates": [],
        "open": [],
        "high": [],
        "low": [],
        "close": [],
        "volume": [],
    }
    for row in klines:
        if len(row) < 6:
            continue
        hist["dates"].append(row[0])
        hist["open"].append(float(row[1]))
        hist["close"].append(float(row[2]))
        hist["high"].append(float(row[3]))
        hist["low"].append(float(row[4]))
        hist["volume"].append(float(row[5]))

    price = (quote or {}).get("price") or (hist["close"][-1] if hist["close"] else None)
    prev = (quote or {}).get("prev_close") or (
        hist["close"][-2] if len(hist["close"]) > 1 else None
    )
    yahoo_symbol = _convert_to_yahoo_symbol(symbol)

    return {
        "market_data": {
            yahoo_symbol: {
                "symbol": symbol,
                "company_name": (quote or {}).get("name"),
                "current_price": price,
                "previous_close": prev,
                "change": price - prev if price and prev else None,
                "change_percent": ((price - prev) / prev * 100) if price and prev else None,
                "volume": (quote or {}).get("volume")
                or (hist["volume"][-1] if hist["volume"] else None),
                "as_of": hist["dates"][-1] if hist["dates"] else None,
                "historical_data": hist,
            }
        },
        "financial_data": {},
        "news_data": [],
        "provider": "tencent-hk",
    }


_EASTMONEY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
}


def _eastmoney_hk_klines(hk_code5: str, beg: str, end: str) -> list[str]:
    """Raw East Money kline scrape for HK stocks (secid '116.xxxxx').

    The plain requests call works from CN servers where both Yahoo and the
    akshare wrapper get dropped. Kline csv fields:
    date,open,close,high,low,volume,amount,amplitude,pct_chg,chg.
    """
    r = requests.get(
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        params={
            "secid": f"116.{hk_code5}",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",  # daily
            "fqt": "1",  # forward-adjusted
            "beg": beg,
            "end": end,
        },
        headers=_EASTMONEY_HEADERS,
        timeout=20,
    )
    r.raise_for_status()
    return (r.json().get("data") or {}).get("klines") or []


def _eastmoney_klines_to_hist(klines: list[str]) -> dict[str, list]:
    dates, opens, closes, highs, lows, volumes = [], [], [], [], [], []
    for row in klines:
        parts = row.split(",")
        if len(parts) < 6:
            continue
        dates.append(parts[0])
        opens.append(float(parts[1]))
        closes.append(float(parts[2]))
        highs.append(float(parts[3]))
        lows.append(float(parts[4]))
        volumes.append(float(parts[5]))
    return {
        "dates": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    }


async def _eastmoney_hk_fetch(symbol: str) -> dict[str, Any] | None:
    """HK snapshot + history via direct East Money scrape (CN-friendly)."""

    def _get():
        end = datetime.now().strftime("%Y%m%d")
        beg = (datetime.now() - timedelta(days=DEFAULT_HISTORY_DAYS)).strftime("%Y%m%d")
        return _eastmoney_hk_klines(_hk_akshare_code(symbol), beg, end)

    klines = await asyncio.to_thread(_get)
    if not klines:
        return None

    hist = _eastmoney_klines_to_hist(klines)
    closes = hist["close"]
    current = closes[-1] if closes else None
    prev = closes[-2] if len(closes) > 1 else None
    yahoo_symbol = _convert_to_yahoo_symbol(symbol)

    return {
        "market_data": {
            yahoo_symbol: {
                "symbol": symbol,
                "current_price": current,
                "previous_close": prev,
                "change": current - prev if current and prev else None,
                "change_percent": ((current - prev) / prev * 100) if current and prev else None,
                "volume": hist["volume"][-1] if hist["volume"] else None,
                "as_of": hist["dates"][-1] if hist["dates"] else None,
                "historical_data": hist,
            }
        },
        "financial_data": {},
        "news_data": [],
        "provider": "eastmoney-hk",
    }


async def _akshare_hk(symbol: str, ak: Any) -> dict[str, Any] | None:
    """HK fallback via the akshare wrapper (often dropped from CN servers;
    the direct East Money scrape above is tried first)."""
    result = await _eastmoney_hk_fetch(symbol)
    if result:
        return result

    def _get_hist():
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=DEFAULT_HISTORY_DAYS)).strftime("%Y%m%d")
        return ak.stock_hk_hist(
            symbol=_hk_akshare_code(symbol),
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
        )

    df = await asyncio.to_thread(_get_hist)
    if df is None or df.empty:
        return None

    col_map = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
    }
    df = df.rename(columns=col_map)
    dates = [str(d) for d in df["date"].tolist()]

    closes = df["close"].tolist()
    current = closes[-1] if closes else None
    prev = closes[-2] if len(closes) > 1 else None
    yahoo_symbol = _convert_to_yahoo_symbol(symbol)

    return {
        "market_data": {
            yahoo_symbol: {
                "symbol": symbol,
                "current_price": current,
                "previous_close": prev,
                "change": current - prev if current and prev else None,
                "change_percent": ((current - prev) / prev * 100) if current and prev else None,
                "volume": df["volume"].iloc[-1] if "volume" in df else None,
                "as_of": dates[-1] if dates else None,
                "historical_data": {
                    "dates": dates,
                    "open": df["open"].tolist(),
                    "high": df["high"].tolist(),
                    "low": df["low"].tolist(),
                    "close": closes,
                    "volume": df["volume"].tolist() if "volume" in df else [],
                    # Exact daily turnover (成交额) for the liquidity layer.
                    **({"amount": df["成交额"].tolist()} if "成交额" in df.columns else {}),
                },
            }
        },
        "financial_data": {},
        "news_data": [],
        "provider": "akshare-hk",
    }
