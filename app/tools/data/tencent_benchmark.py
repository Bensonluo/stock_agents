"""Tencent kline fallback for the market benchmark indexes.

Production (Tencent Cloud host) verified 2026-09-28: yfinance has been 429
rate-limited for 3+ days, so the two market benchmarks — CN ``000001.SS``
(SSE Composite) and US ``^GSPC`` (S&P 500) — both come back empty and every
benchmark-dependent layer (beta/alpha/R²/correlation, market regime, the
sector-benchmark degradation chain) runs blind. Tencent's ifzq kline
endpoint answers from the same box. Row contract: ``[date, open, close,
high, low, volume]`` — close at index 2. US codes requested as ``usINX``
answer under the dotted response key ``us.INX``, so both spellings are
tolerated. Every failure degrades to None — never raises — matching the
benchmark cache's fail-uncached-retry-next-call contract.
"""

from datetime import datetime
from typing import Any

import requests

from app.utils.logging import get_logger

logger = get_logger(__name__)

# Yahoo benchmark symbol -> Tencent market-prefixed index code (the exact
# strings benchmark_ticker_for emits; scope stays on the two market indexes —
# sector ETFs are out).
_TENCENT_INDEX_MAP = {"000001.SS": "sh000001", "^GSPC": "usINX"}

_TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# BENCHMARK_HISTORY_PERIOD is "2y" (~490 trading bars); 800 leaves headroom
# for window growth and API truncation — aligned_returns only needs a
# handful of common dates to regress.
_KLINE_COUNT = 800


def _day_rows(data: Any, code: str) -> list:
    """Kline rows for ``code`` from the response's data node.

    Tries the requested key first, then (for US codes) the dotted market
    form — ``usINX`` requests answer under ``us.INX``. isinstance guards
    throughout: a present-but-null key must not be mistaken for rows.
    """
    if not isinstance(data, dict):
        return []
    node = data.get(code)
    rows = node.get("day") or node.get("qfqday") or [] if isinstance(node, dict) else []
    if rows:
        return rows
    if code.startswith("us") and len(code) > 2:
        node = data.get(f"us.{code[2:]}")
        if isinstance(node, dict):
            rows = node.get("day") or node.get("qfqday") or []
    return rows or []


def tencent_index_history(yahoo_symbol: str) -> dict[str, Any] | None:
    """Benchmark index history from Tencent's kline, in the exact shape
    ``_sync_fetch_benchmark_history`` emits ({symbol, dates, close}, dates
    ``%Y-%m-%d``, symbol still the yahoo form).

    None — never an exception — when the symbol is unmapped, HTTP fails,
    JSON is malformed, or any row breaks the kline contract. A row that
    can't produce a parsed date and a numeric close invalidates the whole
    response: aligned_returns joins on the date strings, so a silently
    garbage row is worse than no benchmark.
    """
    code = _TENCENT_INDEX_MAP.get(yahoo_symbol)
    if not code:
        return None
    try:
        response = requests.get(
            _TENCENT_KLINE_URL,
            params={"param": f"{code},day,,,{_KLINE_COUNT}"},
            headers=_HEADERS,
            timeout=15,
        )
        if response.status_code != 200:
            return None
        payload = response.json()
        rows = _day_rows(payload.get("data") if isinstance(payload, dict) else None, code)

        dates: list[str] = []
        closes: list[float] = []
        for row in rows:
            if not isinstance(row, list | tuple) or len(row) < 6:
                return None
            try:
                day = datetime.strptime(str(row[0])[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
                close = float(row[2])
            except (TypeError, ValueError):
                return None
            dates.append(day)
            closes.append(close)
        if not dates:
            return None
        return {"symbol": yahoo_symbol, "dates": dates, "close": closes}
    except Exception as e:
        logger.warning(f"[tencent-benchmark] failed for {yahoo_symbol}: {e}")
        return None
