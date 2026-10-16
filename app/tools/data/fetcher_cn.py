"""The Chinese A-share chain: the akshare snapshot with its Tencent
kline fallback and the shared Sina financial-indicator mapping. Split from
fetcher.py (behavior-preserving); outside callers keep importing from
fetcher.py."""

import asyncio
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from app.config import get_settings
from app.tools.data.fetcher_common import DEFAULT_HISTORY_DAYS, _cn_tencent_symbol
from app.tools.data.provider_health import record_provider_outcome
from app.utils.logging import get_logger

logger = get_logger(__name__)


async def _akshare_cn(symbol: str, ak: Any) -> dict[str, Any] | None:
    """Chinese A-share via akshare (shared financial mapping lives below)."""

    def _get_hist():
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=DEFAULT_HISTORY_DAYS)).strftime("%Y%m%d")
        return ak.stock_zh_a_hist(
            symbol=symbol, period="daily", start_date=start_date, end_date=end_date, adjust="qfq"
        )

    df = None
    em_error: str | None = None
    try:
        df = await asyncio.to_thread(_get_hist)
    except Exception as e:
        logger.warning(f"[akshare-cn-snap] East Money failed for {symbol}: {e}")
        em_error = f"{type(e).__name__}: {e}"
    if df is None or df.empty:
        record_provider_outcome("akshare-cn", "fail", em_error or "empty East Money frame")
        # push2his.eastmoney.com is domain-blocked from the production CN
        # host (2026-09-27) while Tencent's kline answers from the same box:
        # same window, same qfq basis, EM-shaped frame (volume 股 -> 手).
        # Before this, an EM outage blew through to _akshare_fetch's blanket
        # except and killed the whole snapshot — including the financials
        # chain below, which only runs past this gate.
        fallback = await asyncio.to_thread(
            _sync_fetch_tencent_cn_hist, symbol, ak, DEFAULT_HISTORY_DAYS
        )
        if fallback is not None:
            df = fallback
    else:
        record_provider_outcome("akshare-cn", "ok")
    if df is None or df.empty:
        return None

    col_map = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "涨跌幅": "change_pct",
    }
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
            # Exact daily turnover (成交额, source currency) for the
            # liquidity layer — same key the pipeline's AkShare path emits.
            **({"amount": df["成交额"].tolist()} if "成交额" in df.columns else {}),
        },
    }

    # Same financial-indicator mapping the pipeline's AkShare agent uses —
    # without it this fallback path reports empty metrics and CN symbols
    # landing here lose fundamental scoring AND valuation inputs. Best
    # effort: a failed fetch keeps the market data (the old behavior).
    try:
        financials = await asyncio.to_thread(_sync_fetch_akshare_financials, symbol, ak)
    except Exception as e:
        logger.warning(f"[akshare-CN] financial indicators failed for {symbol}: {e}")
        financials = None

    logger.info(f"[akshare-CN] OK for {symbol}")
    return {
        "market_data": market_data,
        "financial_data": financials or {"metrics": {}},
        "news_data": [],
    }


def _sync_fetch_tencent_cn_hist(symbol: str, ak: Any, days: int) -> pd.DataFrame | None:
    """A-share daily bars from Tencent kline (`stock_zh_a_hist_tx`), East
    Money-column-shaped — the shared CN-history fallback seam.

    push2his.eastmoney.com is domain-blocked from the production CN host
    (verified 2026-09-27: akshare and bare curl both TCP-dropped there),
    while Tencent's kline endpoints answer from the same box. The returned
    frame is renamed to East Money's Chinese column contract with volume
    converted from 股 (shares, the tx contract) to 手 (100-share lots, the
    EM 成交量 contract every existing mapping emits); amount stays yuan on
    both sides. Returns None when Tencent also fails or has no rows —
    callers keep their existing degradation path. Sync on purpose: both
    call sites already run inside asyncio.to_thread workers.
    """
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    try:
        df = ak.stock_zh_a_hist_tx(
            symbol=_cn_tencent_symbol(symbol),
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
        )
    except Exception as e:
        logger.warning(f"[tencent-cn-hist] failed for {symbol}: {e}")
        record_provider_outcome("tencent-cn-hist", "fail", f"{type(e).__name__}: {e}")
        return None
    if df is None or df.empty:
        record_provider_outcome("tencent-cn-hist", "fail", "empty kline frame")
        return None
    record_provider_outcome("tencent-cn-hist", "ok")
    df = df.rename(
        columns={
            "date": "日期",
            "open": "开盘",
            "close": "收盘",
            "high": "最高",
            "low": "最低",
            "volume": "成交量",
            "amount": "成交额",
        }
    )
    if "成交量" in df.columns:
        # 股 -> 手: keep the unit the EM path has always emitted.
        df["成交量"] = df["成交量"] / 100.0
    return df


def _pct_to_ratio(value: Any) -> float | None:
    """Convert an AkShare percentage (31.0 for 31%) to a decimal ratio."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN — AkShare marks missing periods this way
        return None
    return number / 100.0


def _raw_number(value: Any) -> float | None:
    """Raw indicator cell → float; NaN/None/non-numeric → None.

    The unscaled twin of `_pct_to_ratio` for metrics that are already
    ratios or absolute values (current/quick ratio, EPS) and must pass
    through the history block as plain JSON-safe numbers.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN — AkShare marks missing periods this way
        return None
    return number


def _debt_to_equity_from_asset_ratio(pct: Any) -> float | None:
    """Debt/equity from AkShare's debt-to-ASSETS percentage.

    D/E = (D/A) / (1 − D/A) — the same balance sheet, converted because the
    scoring thresholds are equity-based. A ratio of 0 or ≥ 1 means wiped-out
    equity: D/E is undefined there, not merely huge.
    """
    fraction = _pct_to_ratio(pct)
    if fraction is None or not 0.0 < fraction < 1.0:
        return None
    return fraction / (1.0 - fraction)


def _indicator_value(row: Any, *names: str) -> Any:
    """First non-null Sina indicator column matching any alias.

    Live Sina columns carry unit suffixes — ``净资产收益率(%)``,
    ``摊薄每股收益(元)`` — that appear and vanish across akshare releases;
    a bare ``row.get("净资产收益率")`` is an exact-index miss against the
    suffixed name and silently returns None (every CN metric went dark this
    way until caught live). Aliases match exactly OR as the bare name plus
    an open paren, so ``净资产收益率`` matches ``净资产收益率(%)`` but never
    ``加权净资产收益率(%)``. Null/nan cells fall through to the next alias.
    """
    columns = [str(column) for column in row.index]
    for name in names:
        for column in columns:
            if column == name or column.startswith(name + "("):
                value = row[column]
                if value is not None and pd.notna(value):
                    return value
    return None


def _iso_period(cell: Any) -> str | None:
    """Sina 日期 cell → ISO string; anything else → None (row unplaceable).

    akshare delivers ``datetime.date`` cells (verified in its source:
    ``pd.to_datetime(...).dt.date``), but string cells pass through
    unchanged so a schema drift degrades to skipping that row, not the
    whole history block.
    """
    if isinstance(cell, datetime):
        return cell.date().isoformat()
    if isinstance(cell, date):
        return cell.isoformat()
    if isinstance(cell, str) and cell:
        return cell
    return None


def _indicator_metrics(row: Any) -> dict[str, Any]:
    """One Sina indicator row → canonical metric dict.

    Shared by the latest-row metrics block and every indicators_history
    row — one mapper, so the trend points and the headline can never drift
    apart. Canonical names + ratio units: the same keys and thresholds the
    yfinance path emits and scoring.py buckets.
    """
    return {
        "roe": _pct_to_ratio(_indicator_value(row, "净资产收益率")),
        # Total-asset return has worn three spellings across releases.
        "roa": _pct_to_ratio(
            _indicator_value(row, "总资产净利润率", "总资产利润率", "总资产净利率")
        ),
        "gross_margin": _pct_to_ratio(_indicator_value(row, "销售毛利率")),
        "profit_margin": _pct_to_ratio(_indicator_value(row, "销售净利率")),
        "debt_to_asset": _pct_to_ratio(_indicator_value(row, "资产负债率")),
        "debt_to_equity": _debt_to_equity_from_asset_ratio(_indicator_value(row, "资产负债率")),
        "current_ratio": _raw_number(_indicator_value(row, "流动比率")),
        "quick_ratio": _raw_number(_indicator_value(row, "速动比率")),
        # Valuation inputs — without these every A-share scored
        # insufficient_data on the whole scenario-valuation engine.
        # The rows are cumulative report periods, but the earnings
        # method's scenario VALUES are EPS-invariant (eps cancels
        # through price/eps), so a partial-year row distorts only the
        # displayed multiple assumption, never the range.
        "trailing_eps": _raw_number(_indicator_value(row, "摊薄每股收益", "加权每股收益")),
        "earnings_growth": _pct_to_ratio(_indicator_value(row, "净利润增长率")),
        "revenue_growth": _pct_to_ratio(_indicator_value(row, "主营业务收入增长率")),
    }


def _sync_fetch_akshare_financials(symbol: str, ak) -> dict[str, Any] | None:
    """Synchronous AkShare financials fetch — shared by both agent paths."""
    df = ak.stock_financial_analysis_indicator(symbol=symbol)

    if df.empty:
        return None

    latest = df.iloc[-1]
    result = {
        "symbol": symbol,
        "metrics": _indicator_metrics(latest),
        "timestamp": datetime.now().isoformat(),
    }
    # Trend depth: the full dated table rides along as per-period rows.
    # The rows are YTD-cumulative within a reporting year, so consumers
    # must compare same-period-prior-year, never quarter-over-quarter —
    # the shape note lives in the config flag's comment. A row without a
    # placeable date is skipped (the latest-row metrics block above never
    # depended on 日期, so degraded frames keep the old behavior).
    if get_settings().trend_depth_enabled and "日期" in df.columns:
        history = []
        for _, row in df.iterrows():
            period = _iso_period(row.get("日期"))
            if period is None:
                continue
            history.append({"date": period, "metrics": _indicator_metrics(row)})
        if history:
            result["indicators_history"] = history
    return result
