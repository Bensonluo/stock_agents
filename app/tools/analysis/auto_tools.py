"""Auto-fetching analysis tools that only require a symbol parameter.

These wrap the existing analysis functions but automatically fetch data
from the multi-source fetcher, so the LLM only needs to pass a symbol string.
"""

from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.analysis.fundamental import financial_quality
from app.analysis.sentiment import (
    calculate_overall as _calculate_overall,
)
from app.analysis.sentiment import (
    empty_sentiment as _empty_sentiment,
)
from app.analysis.sentiment import (
    score_news,
)
from app.analysis.technical import weekly_sma_summary
from app.analysis.valuation import scenario_valuation
from app.tools.analysis.fundamental import (
    _analyze_financial_health,
    _analyze_growth,
    _analyze_profitability,
    _analyze_valuation,
    _calculate_overall_score,
    _recommendation,
)
from app.tools.analysis.technical import (
    _calculate_indicators,
    _calculate_sentiment,
    _find_support_resistance,
    _generate_signals,
    _to_dataframe,
)
from app.tools.data.fetcher import (
    BENCHMARK_TICKERS,
    benchmark_ticker_for,
    fetch_benchmark_history,
    fetch_cn_sector_benchmark,
    fetch_historical,
    fetch_stock_data,
    sector_benchmark_ticker,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Per-symbol fetch failure memo: once the provider chain has failed REPEAT
# times for a symbol (within TTL), later calls short-circuit WITHOUT hitting
# any provider — the ReAct loop's retry bursts otherwise burn quota and never
# succeed. The instructive error tells the LLM to stop retrying and degrade.
_FETCH_FAILURE_TTL_SECONDS = 300
_FETCH_FAILURE_LIMIT = 2
_fetch_failures: dict[str, tuple[int, float]] = {}


def _record_fetch_failure(symbol: str) -> int:
    import time

    now = time.monotonic()
    count, first_at = _fetch_failures.get(symbol, (0, now))
    if now - first_at > _FETCH_FAILURE_TTL_SECONDS:
        count, first_at = 0, now
    count += 1
    _fetch_failures[symbol] = (count, first_at)
    return count


def _reset_fetch_failures(symbol: str) -> None:
    _fetch_failures.pop(symbol, None)


def _fetch_failures_exceeded(symbol: str) -> bool:
    import time

    entry = _fetch_failures.get(symbol)
    if not entry:
        return False
    count, first_at = entry
    if time.monotonic() - first_at > _FETCH_FAILURE_TTL_SECONDS:
        return False
    return count >= _FETCH_FAILURE_LIMIT


def data_unavailable_error(symbol: str) -> dict[str, Any]:
    """Instructive error that steers the LLM out of retry loops."""
    count = _fetch_failures.get(symbol, (0, 0.0))[0]
    return {
        "error": (
            f"数据源已确认无法获取 {symbol}（本轮已失败 {count} 次，短期内重试不会成功，"
            f"请勿再调用任何数据获取工具）。请直接调用 generate_report 生成报告，"
            f"并在报告中明确说明该标的数据不可用。"
        ),
        "symbol": symbol,
        "data_available": False,
    }


async def _attach_benchmark(market: dict[str, Any], symbol: str) -> dict[str, Any]:
    """Attach the market's benchmark index to a ReAct market block.

    Same contract as the pipeline data agent: benchmark present -> the risk
    tools can regress beta/alpha/R²; fetch failure -> key absent, beta stays
    None exactly as before benchmarks existed. The 30-min fetcher cache
    keeps per-symbol ReAct calls from re-downloading the same index.
    """
    if not market:
        return market
    bench = await fetch_benchmark_history(benchmark_ticker_for(symbol))
    if bench is not None:
        market["benchmark_historical_data"] = bench
    # Sector-relative annotation (same contract as the pipeline data
    # agent): only when the market block carries a mapped sector does the
    # extra ETF fetch happen; the 30-min cache makes it free across the
    # per-symbol tool calls of one analysis.
    sector_ticker = sector_benchmark_ticker(market.get("sector"))
    if sector_ticker:
        sector_bench = await fetch_benchmark_history(sector_ticker)
        if sector_bench is not None:
            market["sector_benchmark_historical_data"] = sector_bench
    # CN parity: the East Money industry board replaces the SPDR ETF
    # mapping for A-shares (Chinese sector names have no US ETF
    # vocabulary). Same key, same failure contract as above.
    if benchmark_ticker_for(symbol) == BENCHMARK_TICKERS["cn"]:
        cn_bench = await fetch_cn_sector_benchmark(symbol)
        if cn_bench is not None:
            market["sector_benchmark_historical_data"] = cn_bench
    return market


async def _fetch_and_split(symbol: str) -> dict[str, Any] | None:
    """Fetch stock data and split into components.

    Tries both fetch_stock_data (snapshot) and fetch_historical (OHLC series).
    If the snapshot's historical_data is empty, supplements it from fetch_historical.
    If the snapshot fails entirely (all providers down — e.g. CN-hosted servers
    where Yahoo blocks), falls back to fetch_historical alone and builds the
    market block from the series (current price = last close): history is the
    critical data, the snapshot is enrichment.
    """
    if _fetch_failures_exceeded(symbol):
        return data_unavailable_error(symbol)

    data = await fetch_stock_data(symbol)

    if not data:
        failures = _record_fetch_failure(symbol)
        if failures >= _FETCH_FAILURE_LIMIT:
            return data_unavailable_error(symbol)
        # Snapshot chain exhausted — history alone can still power the analysis.
        try:
            hist = await fetch_historical(symbol, period="3y")
        except Exception as e:
            logger.warning(f"[auto_tools] historical fallback failed for {symbol}: {e}")
            _record_fetch_failure(symbol)
            return data_unavailable_error(symbol)
        if isinstance(hist, dict) and hist.get("dates") and "error" not in hist:
            _reset_fetch_failures(symbol)
            closes = hist.get("close") or []
            last_close = closes[-1] if closes else None
            prev_close = closes[-2] if len(closes) > 1 else None
            market = {
                "symbol": symbol,
                "current_price": last_close,
                "previous_close": prev_close,
                "change": (last_close - prev_close) if last_close and prev_close else None,
                "change_percent": (
                    ((last_close - prev_close) / prev_close * 100)
                    if last_close and prev_close
                    else None
                ),
                "volume": (hist.get("volume") or [None])[-1],
                "as_of": (hist.get("dates") or [None])[-1],
                "historical_data": {
                    "dates": hist["dates"],
                    "open": hist.get("open", []),
                    "high": hist.get("high", []),
                    "low": hist.get("low", []),
                    "close": hist.get("close", []),
                    "volume": hist.get("volume", []),
                },
            }
            logger.info(
                f"[auto_tools] snapshot chain failed for {symbol}; "
                f"built market block from historical series ({len(hist['dates'])} bars)"
            )
            return {
                "market_data": {symbol: await _attach_benchmark(market, symbol)},
                "financial_data": {symbol: {}},
                "news_data": [],
            }
        return None

    _reset_fetch_failures(symbol)
    market = data.get("market_data", {}) or {}
    hist_block = market.get("historical_data") or {}

    # If snapshot didn't include historical (e.g. Finnhub free tier / yfinance 429),
    # pull the OHLC series from fetch_historical and merge it in.
    if not hist_block.get("dates"):
        try:
            hist = await fetch_historical(symbol, period="3y")
            if isinstance(hist, dict) and hist.get("dates") and "error" not in hist:
                _reset_fetch_failures(symbol)
                market["historical_data"] = {
                    "dates": hist["dates"],
                    "open": hist.get("open", []),
                    "high": hist.get("high", []),
                    "low": hist.get("low", []),
                    "close": hist.get("close", []),
                    "volume": hist.get("volume", []),
                }
        except Exception as e:
            logger.warning(f"[auto_tools] historical fetch fallback failed for {symbol}: {e}")

    return {
        "market_data": {symbol: await _attach_benchmark(market, symbol)},
        "financial_data": {symbol: data.get("financial_data", {})},
        "news_data": data.get("news_data", []),
    }


def _weekly_sma(symbol: str, hist: dict[str, Any]) -> dict[str, Any]:
    """Weekly SMA trend features; evidence list is dropped to save LLM tokens."""
    try:
        return weekly_sma_summary(hist, symbol=symbol, include_evidence=False)
    except Exception as e:
        logger.warning(f"[auto_tools] weekly SMA summary failed for {symbol}: {e}")
        return {"status": "error", "reason": str(e)}


class AnalyzeTechnicalSimpleInput(BaseModel):
    symbol: str = Field(description="Stock symbol to analyze (e.g., 'AAPL', '600000')")


@tool(args_schema=AnalyzeTechnicalSimpleInput)
async def analyze_technical(symbol: str) -> dict[str, Any]:
    """Compute technical indicators (RSI, MACD, Bollinger Bands, support/resistance).
    Automatically fetches the latest market data.
    """
    data = await _fetch_and_split(symbol)
    if not data:
        return data_unavailable_error(symbol)
    if data.get("data_available") is False:
        return data

    market = data["market_data"].get(symbol, {})
    hist = market.get("historical_data")
    if not hist:
        _record_fetch_failure(symbol)
        return data_unavailable_error(symbol)

    try:
        df = _to_dataframe(hist)
        if df.empty or len(df) < 20:
            return {"error": f"Insufficient data points for {symbol} ({len(df)} rows)"}

        indicators = _calculate_indicators(df)
        signals = _generate_signals(df, indicators)
        support, resistance = _find_support_resistance(df)
        sentiment = _calculate_sentiment(signals, indicators)

        return {
            "symbol": symbol,
            "current_price": market.get("current_price"),
            "indicators": indicators,
            "signals": signals,
            "support": support,
            "resistance": resistance,
            "sentiment": sentiment,
            "weekly_sma": _weekly_sma(symbol, hist),
        }
    except Exception as e:
        logger.error(f"Technical analysis failed for {symbol}: {e}")
        return {"error": f"Technical analysis failed: {e}"}


class AnalyzeFundamentalSimpleInput(BaseModel):
    symbol: str = Field(description="Stock symbol to analyze (e.g., 'AAPL', '600000')")


@tool(args_schema=AnalyzeFundamentalSimpleInput)
async def analyze_fundamental(symbol: str) -> dict[str, Any]:
    """Evaluate financial health, profitability, and valuation (PE, PB, ROE, etc.).
    Automatically fetches the latest financial data.
    """
    data = await _fetch_and_split(symbol)
    if not data:
        return data_unavailable_error(symbol)
    if data.get("data_available") is False:
        return data

    financial = data["financial_data"].get(symbol, {})
    mkt = data["market_data"].get(symbol, {})
    metrics = financial.get("metrics", {})

    profitability = _analyze_profitability(metrics)
    valuation = _analyze_valuation(metrics, mkt)
    health = _analyze_financial_health(metrics)
    growth = _analyze_growth(financial)
    overall = _calculate_overall_score(profitability, valuation, health, growth)

    return {
        "symbol": symbol,
        "profitability": profitability,
        "valuation": valuation,
        "financial_health": health,
        "growth": growth,
        "overall_score": overall,
        "recommendation": _recommendation(overall["score"]),
        "quality": _financial_quality_view(symbol, financial),
    }


class AnalyzeValuationSimpleInput(BaseModel):
    symbol: str = Field(description="Stock symbol to analyze (e.g., 'AAPL', '600000')")


@tool(args_schema=AnalyzeValuationSimpleInput)
async def analyze_valuation(symbol: str) -> dict[str, Any]:
    """Estimate a Bear/Base/Bull value RANGE with stated assumptions and a
    sensitivity table. Returns a range, never a single target price.
    Automatically fetches the latest financial data.
    """
    data = await _fetch_and_split(symbol)
    if not data:
        return data_unavailable_error(symbol)
    if data.get("data_available") is False:
        return data

    financial = data["financial_data"].get(symbol, {})
    mkt = data["market_data"].get(symbol, {})
    metrics = financial.get("metrics", {})

    result = scenario_valuation(
        symbol=symbol,
        current_price=mkt.get("current_price"),
        trailing_eps=metrics.get("trailing_eps"),
        ps_ratio=metrics.get("ps_ratio"),
        earnings_growth=metrics.get("earnings_growth"),
        revenue_growth=metrics.get("revenue_growth"),
        source="financial_metrics",
    )
    # Evidence trail stays server-side; the LLM needs scenarios + assumptions.
    result.pop("evidence", None)
    return result


def _financial_quality_view(symbol: str, financial: dict[str, Any]) -> dict[str, Any]:
    """Compact statement-quality summary (status, trend verdicts, red flags)."""
    try:
        quality = financial_quality(financial, symbol=symbol, source="financial_statements")
    except Exception as e:
        logger.warning(f"[auto_tools] financial quality failed for {symbol}: {e}")
        return {"status": "error", "reason": str(e)}
    return {
        "status": quality["status"],
        "revenue_trend": (
            {
                "cagr": (quality.get("revenue_trend") or {}).get("cagr"),
            }
            if quality.get("revenue_trend")
            else None
        ),
        "cash_quality": quality.get("cash_quality"),
        "red_flags": quality.get("red_flags", []),
    }


class AnalyzeSentimentSimpleInput(BaseModel):
    symbol: str = Field(description="Stock symbol to analyze")


@tool(args_schema=AnalyzeSentimentSimpleInput)
async def analyze_sentiment(symbol: str) -> dict[str, Any]:
    """Assess market sentiment from recent news for a stock.
    Automatically fetches the latest news data.
    """
    data = await _fetch_and_split(symbol)
    if not data:
        return data_unavailable_error(symbol)
    if data.get("data_available") is False:
        return data

    news_data = data["news_data"]
    if not news_data:
        return {
            "symbol": symbol,
            "sentiment_by_symbol": {symbol: _empty_sentiment()},
            "overall_sentiment": {"sentiment": "neutral", "score": 0, "note": "No news available"},
        }

    symbol_news = [
        n
        for n in news_data
        if symbol in n.get("related_symbols", [])
        or n.get("original_symbol") == symbol
        or symbol.lower() in (n.get("title", "") + n.get("summary", "")).lower()
    ]
    if not symbol_news:
        symbol_news = news_data

    # The canonical shared computation — this tool only owns fetch + shell.
    # Its previous inline keyword copy had drifted from the canonical module
    # (no recency decay since iteration 24).
    result = score_news(symbol_news)

    return {
        "symbol": symbol,
        "sentiment": result,
        "overall_sentiment": _calculate_overall({symbol: result}),
        "headlines": [n.get("title", "") for n in symbol_news[:5]],
    }


class AssessRiskSimpleInput(BaseModel):
    symbol: str = Field(description="Stock symbol to assess risk for")


@tool(args_schema=AssessRiskSimpleInput)
async def assess_risk(symbol: str) -> dict[str, Any]:
    """Calculate risk metrics (volatility, VaR/CVaR, beta, max drawdown, risk score).
    Automatically fetches the latest market data.
    """
    from app.tools.risk.assessment import assess_symbol

    data = await _fetch_and_split(symbol)
    if not data:
        return data_unavailable_error(symbol)
    if data.get("data_available") is False:
        return data

    # The canonical shared computation — this tool only owns fetch + shell.
    # Its previous inline copy had drifted from the engine: unguarded
    # percentile VaR (no >=20-return guard) and no CVaR at all.
    market = data["market_data"].get(symbol, {})
    return assess_symbol(symbol, market)


class GetStockOverviewInput(BaseModel):
    symbol: str = Field(description="Stock symbol (e.g., 'AAPL', '600000')")


@tool(args_schema=GetStockOverviewInput)
async def get_stock_overview(symbol: str) -> dict[str, Any]:
    """Get a quick stock overview: company name, current price, change,
    sector, market cap, 52-week range. Use this to fill in the
    market_summary section of a report.
    """
    if _fetch_failures_exceeded(symbol):
        return data_unavailable_error(symbol)
    data = await fetch_stock_data(symbol)
    if not data:
        return (
            data_unavailable_error(symbol)
            if _record_fetch_failure(symbol) >= _FETCH_FAILURE_LIMIT
            else {"error": f"Could not fetch data for {symbol}"}
        )
    _reset_fetch_failures(symbol)
    m = data.get("market_data", {})
    return {
        "symbol": symbol,
        "company_name": m.get("company_name"),
        "current_price": m.get("current_price"),
        "change": m.get("change"),
        "change_percent": m.get("change_percent"),
        "volume": m.get("volume"),
        "market_cap": m.get("market_cap"),
        "sector": m.get("sector"),
        "currency": m.get("currency"),
        "exchange": m.get("exchange"),
        "52_week_high": m.get("52_week_high"),
        "52_week_low": m.get("52_week_low"),
    }
