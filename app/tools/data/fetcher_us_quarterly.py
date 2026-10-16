"""US quarterly income statements from East Money (akshare F10 seam).

Production gap (verified 2026-09-25 in the deploy container): the Tencent
Cloud host is rate-limited by Yahoo on every endpoint, so the yfinance
quarterly frames behind ``trend_depth_enabled`` are dark there — the US leg
of ``quarterly_statement_trends`` never fires. akshare's
``stock_financial_us_report_em`` (综合损益表, 单季报) serves PRE-differenced
discrete quarters over the same CN network the akshare CN legs already use.

The seam is fill-only at the data-agent layer: a live yfinance result keeps
precedence. Every failure here degrades to ``None`` → the
``statements_quarterly`` key stays absent, exactly like the yfinance leg.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.backtest import stamp_visibility
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Wire row → East Money ITEM_NAME candidates, most specific first. The trend
# consumer (quarterly_statement_trends) reads exactly Total Revenue / Net
# Income; revenue falls back 营业收入 when 主营收入 is absent, net income
# prefers the parent-attributed headline (yfinance Net Income semantics).
EM_ROW_CANDIDATES: dict[str, tuple[str, ...]] = {
    "Total Revenue": ("主营收入", "营业收入"),
    "Net Income": ("归属于母公司股东净利润", "净利润", "持续经营净利润"),
}

# A row needs two usable points before it can show a direction — one point
# is a level (mirrors the consumer's own threshold).
_MIN_POINTS = 2


def quarterly_income_from_em(df: pd.DataFrame | None) -> dict[str, Any] | None:
    """Long East Money frame → statements_quarterly wire block.

    Input is one row per (REPORT_DATE, ITEM_NAME, AMOUNT), provider order
    (newest-first); output matches the yfinance converter's contract:
    ``{"income_statement": {"dates": [...], "data": {...}, "visible_from":
    [...]}}`` with dates oldest → newest and per-row lists index-aligned to
    dates (missing/NaN quarters are None, dropped per-row by the consumer's
    window). Duplicate (date, item) rows keep the LAST amount — the
    restatement wins, matching a provider re-publish. Returns None when no
    wire row reaches the two-point floor.
    """
    if df is None or df.empty:
        return None
    dates = sorted({str(d)[:10] for d in df["REPORT_DATE"]})
    data: dict[str, list[float | None]] = {}
    for row_name, candidates in EM_ROW_CANDIDATES.items():
        for item in candidates:
            mask = df["ITEM_NAME"] == item
            grouped = (
                df.loc[mask, ["REPORT_DATE", "AMOUNT"]]
                .assign(REPORT_DATE=lambda f: f["REPORT_DATE"].map(lambda d: str(d)[:10]))
                .groupby("REPORT_DATE")["AMOUNT"]
                .last()
            )
            values: list[float | None] = []
            for d in dates:
                amount = grouped.get(d)
                if amount is None or pd.isna(amount):
                    values.append(None)
                else:
                    values.append(float(amount))
            if sum(v is not None for v in values) >= _MIN_POINTS:
                data[row_name] = values
                break
    if not data:
        return None
    return {"income_statement": stamp_visibility({"dates": dates, "data": data})}


def fetch_us_quarterly_income_em(symbol: str) -> dict[str, Any] | None:
    """Fetch + convert one US symbol's quarterly income statements.

    Sync (requests under the hood) — callers keep it loop-safe via
    asyncio.to_thread. None on ImportError (akshare absent), endpoint
    failure, or an unusable frame: the caller leaves the
    statements_quarterly key absent.
    """
    try:
        import akshare as ak
    except ImportError:
        return None
    try:
        df = ak.stock_financial_us_report_em(stock=symbol, symbol="综合损益表", indicator="单季报")
    except Exception as exc:  # endpoint dark / rate limit / shape change
        logger.warning(f"[us_quarterly_em] endpoint dark for {symbol}: {exc}")
        return None
    try:
        return quarterly_income_from_em(df)
    except Exception as exc:  # unexpected frame shape
        logger.warning(f"[us_quarterly_em] unusable frame for {symbol}: {exc}")
        return None
