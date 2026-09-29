"""Market-index and CN industry-board benchmarks for beta/alpha/R²
regression, including the sector-ETF Sina third leg. Split from fetcher.py
(behavior-preserving); outside callers keep importing from fetcher.py."""

import asyncio
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from app.tools.data.fetcher_common import (
    DEFAULT_HISTORY_DAYS,
    _cache_get,
    _cache_set,
    _is_chinese_symbol,
)
from app.tools.data.fetcher_us import _sina_us_hist
from app.tools.data.provider_health import record_provider_outcome
from app.tools.data.tencent_benchmark import tencent_index_history
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Benchmarks for beta/alpha/R² regression, shared with the pipeline data
# agent: S&P 500 for international names, SSE Composite for A-shares.
# Fetched through the shared 30-min cache so ReAct tool calls (one symbol
# at a time) never re-fetch the same index within one analysis session.
BENCHMARK_TICKERS = {"us": "^GSPC", "cn": "000001.SS"}
BENCHMARK_HISTORY_PERIOD = "2y"

# yfinance sector string -> SPDR sector ETF. Sector-relative regression
# (beta against your own industry, not just the broad index) only
# annotates when the sector is known AND maps — CN spot rows carry no
# sector, so A-shares simply stay on the market benchmark.
SECTOR_BENCHMARK_ETFS = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Energy": "XLE",
    "Healthcare": "XLV",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Industrials": "XLI",
    "Basic Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}


def benchmark_ticker_for(symbol: str) -> str:
    """S&P 500 for international symbols; SSE Composite for 6-digit A-shares."""
    if _is_chinese_symbol(symbol):
        return BENCHMARK_TICKERS["cn"]
    return BENCHMARK_TICKERS["us"]


def sector_benchmark_ticker(sector: str | None) -> str | None:
    """SPDR sector ETF for a yfinance sector string; None when unmapped."""
    if not sector:
        return None
    return SECTOR_BENCHMARK_ETFS.get(str(sector).strip())


# The benchmark chain's Sina leg serves exactly these tickers. Tencent's
# ifzq kline endpoint returns full history for indexes only (usINX: 801
# rows) and exactly one row for US ETFs at any count — probed 2026-09-29 —
# so the SPDR sector benchmarks have no Tencent fallback by endpoint
# design; Sina's US daily (full history, production-host-verified since
# iteration 91) is their last resort under Yahoo rate limiting.
_SECTOR_ETF_TICKERS = frozenset(SECTOR_BENCHMARK_ETFS.values())


def _sync_fetch_benchmark_history(yahoo_symbol: str) -> dict[str, Any] | None:
    """Benchmark index history as a dates/close dict — the shape
    ``aligned_returns`` regresses against (same as historical_data)."""
    import yfinance as yf

    def _tencent_with_health() -> dict[str, Any] | None:
        bench = tencent_index_history(yahoo_symbol)
        record_provider_outcome(
            "tencent-benchmark",
            "ok" if bench is not None else "fail",
            None if bench is not None else "no benchmark data",
        )
        return bench

    yf_error: str | None = None
    try:
        df = yf.Ticker(yahoo_symbol).history(period=BENCHMARK_HISTORY_PERIOD, interval="1d")
    except Exception as e:
        # Rate-limited yfinance (the production CN host's documented state
        # since 2026-09-25) raises before any frame exists — the Tencent
        # fallback below is the seam that keeps benchmarks alive.
        df = pd.DataFrame()
        yf_error = f"{type(e).__name__}: {e}"
    if df.empty or "Close" not in df.columns:
        # yfinance dark → Tencent kline for the two market indexes; same
        # {symbol, dates, close} contract. Tencent failing too keeps the
        # None semantics (fail-uncached, retried next invocation).
        record_provider_outcome("yfinance-benchmark", "fail", yf_error or "empty history frame")
        return _tencent_with_health()
    dates = [d.strftime("%Y-%m-%d") for d in df.index]
    if not dates:
        record_provider_outcome("yfinance-benchmark", "fail", "history frame has no dates")
        return _tencent_with_health()
    record_provider_outcome("yfinance-benchmark", "ok")
    return {"symbol": yahoo_symbol, "dates": dates, "close": [float(c) for c in df["Close"]]}


async def fetch_benchmark_history(yahoo_symbol: str) -> dict[str, Any] | None:
    """Cached benchmark history (30-min TTL); None when the fetch fails.

    Only successful fetches are cached — a failed index call is retried on
    the next tool invocation rather than poisoning the cache with None.
    """
    cache_key = f"bench_{yahoo_symbol}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    try:
        bench = await asyncio.to_thread(_sync_fetch_benchmark_history, yahoo_symbol)
    except Exception as e:
        logger.warning(f"Benchmark history unavailable for {yahoo_symbol}: {e}")
        bench = None
    if bench is None and yahoo_symbol in _SECTOR_ETF_TICKERS:
        # Third leg, sector ETFs only: tencent_index_history returns None for
        # the unmapped SPDR tickers by design (iteration 96), so a Yahoo-dark
        # host left US sector_relative without regression input. Sina serves
        # full SPDR history and answers from the production host.
        hist = await _sina_us_hist(yahoo_symbol, BENCHMARK_HISTORY_PERIOD)
        bench = (
            {"symbol": yahoo_symbol, "dates": hist["dates"], "close": hist["close"]}
            if hist is not None
            else None
        )
        record_provider_outcome(
            "sina-benchmark",
            "ok" if bench is not None else "fail",
            None if bench is not None else "no sector ETF history",
        )
    if bench is not None:
        _cache_set(cache_key, bench)
    return bench


def _sync_cn_industry_name(symbol: str) -> str | None:
    """Industry board name for an A-share via East Money individual info."""
    import akshare as ak

    df = ak.stock_individual_info_em(symbol=symbol)
    if df is None or df.empty or "item" not in df.columns:
        return None
    rows = df[df["item"] == "行业"]
    if rows.empty:
        return None
    industry = str(rows.iloc[0]["value"]).strip()
    return industry or None


def _sync_cn_industry_history(industry: str) -> dict[str, Any] | None:
    """East Money industry-board index history as a dates/close dict.

    Same shape ``aligned_returns`` consumes for the sector regression —
    board index closes regress against stock closes exactly like the SPDR
    ETF path does for US sectors.
    """
    import akshare as ak

    end = datetime.now()
    start = end - timedelta(days=DEFAULT_HISTORY_DAYS)
    df = ak.stock_board_industry_hist_em(
        symbol=industry,
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        period="日k",
        adjust="",
    )
    if df is None or df.empty or "收盘" not in df.columns:
        return None
    dates = [str(d) for d in df["日期"].tolist()]
    if not dates:
        return None
    return {
        "symbol": industry,
        "dates": dates,
        "close": [float(c) for c in df["收盘"].tolist()],
    }


async def fetch_cn_sector_benchmark(symbol: str) -> dict[str, Any] | None:
    """CN industry-board benchmark for an A-share; None on any failure.

    Two East Money calls behind the shared 30-min cache: symbol → industry
    name (cached per symbol), industry → board history (cached per industry
    so a same-industry portfolio pays one fetch). Only successes are cached,
    matching the market-benchmark contract.
    """
    name_key = f"cn_industry_name_{symbol}"
    industry = _cache_get(name_key)
    if industry is None:
        try:
            industry = await asyncio.to_thread(_sync_cn_industry_name, symbol)
        except Exception as e:
            logger.warning(f"CN industry lookup failed for {symbol}: {e}")
            return None
        if not industry:
            return None
        _cache_set(name_key, industry)

    hist_key = f"cn_industry_hist_{industry}"
    bench = _cache_get(hist_key)
    if bench is not None:
        return bench
    try:
        bench = await asyncio.to_thread(_sync_cn_industry_history, industry)
    except Exception as e:
        logger.warning(f"CN industry board history failed for {industry}: {e}")
        return None
    if bench is not None:
        _cache_set(hist_key, bench)
    return bench
