"""Data collection agent for fetching stock market data."""

import asyncio
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import yfinance as yf

from app.agents.base import BaseAgent
from app.orchestration.state import AgentState
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Semaphore to cap concurrent yfinance calls and avoid rate-limiting
_yfinance_semaphore = asyncio.Semaphore(5)

# Same idea for AkShare's East Money endpoints: bounded concurrency keeps
# multi-symbol A-share runs from hammering the source while still fetching
# per-symbol history/financials in parallel instead of one-by-one.
_akshare_semaphore = asyncio.Semaphore(5)

# Single definition of the shared history window (also used by the ReAct
# fetcher) — changing the warm-up horizon must not require two edits.
from app.tools.data.fetcher import DEFAULT_HISTORY_DAYS, fetch_stock_data  # noqa: E402

# Benchmarks for beta/alpha/R² regression in the risk stage, fetched once per
# run (never per symbol): S&P 500 for international names, SSE Composite for
# A-shares. Without these the risk engine can compute VaR/CVaR/volatility but
# beta is permanently insufficient_data — the engine supported benchmarks all
# along, the data layer just never supplied them.
BENCHMARK_TICKERS = {"us": "^GSPC", "cn": "000001.SS"}

# Two years of daily benchmark bars ≈ 500 observations — plenty for the
# 20-return minimum the risk helpers enforce, and one index round-trip.
BENCHMARK_HISTORY_PERIOD = "2y"


def _benchmark_ticker_for(symbol: str) -> str:
    """S&P 500 for international symbols; SSE Composite for 6-digit A-shares."""
    if symbol.isdigit() and len(symbol) == 6:
        return BENCHMARK_TICKERS["cn"]
    return BENCHMARK_TICKERS["us"]


def _sync_fetch_benchmark_history(yahoo_symbol: str) -> dict[str, Any] | None:
    """Synchronous benchmark index history; None when the fetch yields nothing.

    Returns a dates/close dict shaped exactly like a symbol's
    ``historical_data`` block — what ``aligned_returns`` regresses against.
    """
    ticker = yf.Ticker(yahoo_symbol)
    hist = ticker.history(period=BENCHMARK_HISTORY_PERIOD, interval="1d")
    if hist.empty or "Close" not in hist.columns:
        return None
    dates = [d.strftime("%Y-%m-%d") for d in hist.index]
    closes = [float(c) for c in hist["Close"].tolist()]
    if not dates:
        return None
    return {"symbol": yahoo_symbol, "dates": dates, "close": closes}


def _yfinance_debt_to_equity_ratio(value: Any) -> float | None:
    """Convert yfinance's percentage-valued debtToEquity to a decimal ratio."""
    if value is None:
        return None
    return float(value) / 100.0


def convert_to_yahoo_symbol(symbol: str) -> str:
    """Convert local symbol format to Yahoo Finance format.

    Args:
        symbol: Stock symbol in various formats

    Returns:
        Yahoo Finance compatible symbol

    Examples:
        601888 -> 601888.SS (Shanghai)
        000001 -> 000001.SZ (Shenzhen)
        300001 -> 300001.SZ (Shenzhen ChiNext)
        AAPL -> AAPL (US stocks unchanged)
        3690.HK -> 3690.HK (HK stocks unchanged)
    """
    # US stocks (1-5 letters) - unchanged
    if symbol.isalpha() and len(symbol) <= 5:
        return symbol

    # HK stocks - unchanged
    if ".HK" in symbol.upper():
        return symbol.upper()

    # Chinese stocks (6 digits) - add exchange suffix
    if symbol.isdigit() and len(symbol) == 6:
        if symbol.startswith("6"):
            # Shanghai Stock Exchange (600xxx, 601xxx, 603xxx, 605xxx)
            return f"{symbol}.SS"
        elif symbol.startswith("0") or symbol.startswith("3"):
            # Shenzhen Stock Exchange (000xxx, 001xxx, 002xxx, 003xxx) or ChiNext (300xxx)
            return f"{symbol}.SZ"
        else:
            # Default to Shanghai for other codes
            return f"{symbol}.SS"

    return symbol


def detect_symbol_type(symbol: str) -> str:
    """Detect the type/market of a stock symbol.

    Args:
        symbol: Stock symbol

    Returns:
        Market type: 'us', 'cn', 'hk', or 'unknown'
    """
    s = symbol.upper()

    # US stocks: 1-5 letters
    if s.isalpha() and len(s) <= 5:
        return "us"

    # HK stocks: digits + .HK
    if ".HK" in s:
        return "hk"

    # Chinese stocks: 6 digits
    if s.isdigit() and len(s) == 6:
        return "cn"

    return "unknown"


def _sync_fetch_market_data(yahoo_symbol: str, symbol: str, hist_converter) -> dict[str, Any]:
    """Synchronous yfinance market data fetch — runs in thread pool."""
    ticker = yf.Ticker(yahoo_symbol)
    info = ticker.info

    end_date = datetime.now()
    start_date = end_date - timedelta(days=DEFAULT_HISTORY_DAYS)
    hist = ticker.history(start=start_date, end=end_date)

    if hist.empty:
        return {}

    hist_data = hist_converter(hist)

    current_price = info.get("currentPrice") or info.get("regularMarketPrice")
    previous_close = info.get("previousClose")

    change = None
    change_percent = None
    if current_price and previous_close:
        change = current_price - previous_close
        change_percent = (change / previous_close) * 100

    # as_of is the data cutoff every downstream metric must respect: the last
    # trading bar when available, else the fetch time.
    hist_dates = hist_data.get("dates") or []
    as_of = hist_dates[-1] if hist_dates else datetime.now().date().isoformat()

    return {
        "symbol": symbol,
        "yahoo_symbol": yahoo_symbol,
        "current_price": current_price,
        "previous_close": previous_close,
        "change": change,
        "change_percent": change_percent,
        "volume": info.get("volume"),
        "avg_volume": info.get("averageVolume"),
        "market_cap": info.get("marketCap"),
        "52_week_high": info.get("fiftyTwoWeekHigh"),
        "52_week_low": info.get("fiftyTwoWeekLow"),
        "company_name": info.get("longName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "description": info.get("longBusinessSummary"),
        "as_of": as_of,
        "historical_data": hist_data,
        "timestamp": datetime.now().isoformat(),
    }


def _sync_fetch_financial_data(yahoo_symbol: str, symbol: str, stmt_converter) -> dict[str, Any]:
    """Synchronous yfinance financial data fetch — runs in thread pool."""
    ticker = yf.Ticker(yahoo_symbol)

    income_stmt = ticker.income_stmt
    balance_sheet = ticker.balance_sheet
    cash_flow = ticker.cashflow
    info = ticker.info

    earnings_dates = []
    if ticker.earnings_dates is not None:
        earnings_dates = ticker.earnings_dates.to_dict("records")

    return {
        "symbol": symbol,
        "metrics": {
            "roe": info.get("returnOnEquity"),
            "roa": info.get("returnOnAssets"),
            "profit_margin": info.get("profitMargins"),
            "operating_margin": info.get("operatingMargins"),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "trailing_eps": info.get("trailingEps"),
            "pb_ratio": info.get("priceToBook"),
            "ps_ratio": info.get("priceToSalesTrailing12Months"),
            "peg_ratio": info.get("pegRatio"),
            "enterprise_value": info.get("enterpriseValue"),
            "ev_ebitda": info.get("enterpriseToEbitda"),
            "debt_to_equity": _yfinance_debt_to_equity_ratio(info.get("debtToEquity")),
            "current_ratio": info.get("currentRatio"),
            "quick_ratio": info.get("quickRatio"),
            "total_cash": info.get("totalCash"),
            "total_debt": info.get("totalDebt"),
            "total_revenue": info.get("totalRevenue"),
            "revenue_per_share": info.get("revenuePerShare"),
            "dividend_yield": info.get("dividendYield"),
            "dividend_rate": info.get("dividendRate"),
            "payout_ratio": info.get("payoutRatio"),
            "revenue_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
        },
        "metric_units": {
            "roe": "ratio",
            "roa": "ratio",
            "profit_margin": "ratio",
            "operating_margin": "ratio",
            "debt_to_equity": "ratio",
            "dividend_yield": "ratio",
            "payout_ratio": "ratio",
            "revenue_growth": "ratio",
            "earnings_growth": "ratio",
        },
        "income_statement": stmt_converter(income_stmt) if income_stmt is not None else {},
        "balance_sheet": stmt_converter(balance_sheet) if balance_sheet is not None else {},
        "cash_flow": stmt_converter(cash_flow) if cash_flow is not None else {},
        "earnings_dates": earnings_dates,
        "timestamp": datetime.now().isoformat(),
    }


def _sync_fetch_news(yahoo_symbol: str, symbol: str) -> list[dict[str, Any]]:
    """Synchronous yfinance news fetch — runs in thread pool."""
    ticker = yf.Ticker(yahoo_symbol)
    news = ticker.news

    if not news:
        return []

    articles = []
    for item in news[:20]:
        content = item.get("content", {})
        title = content.get("title") or item.get("title")
        summary = content.get("summary") or item.get("summary")

        link = None
        if content.get("canonicalUrl"):
            link = content["canonicalUrl"].get("url")
        if not link and item.get("link"):
            link = item.get("link")

        provider = content.get("provider", {})
        source = provider.get("displayName") or item.get("publisher")
        published = content.get("pubDate") or item.get("providerPublishTime")

        related = item.get("relatedTickers", [])
        if symbol not in related:
            related.append(symbol)
        if yahoo_symbol not in related:
            related.append(yahoo_symbol)

        if title:
            articles.append(
                {
                    "title": title,
                    "link": link,
                    "published": published,
                    "source": source,
                    "summary": summary,
                    "related_symbols": related,
                    "original_symbol": symbol,
                }
            )

    return articles


def _dedup_news(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge duplicate articles (same link, else title) across symbol fetches.

    yfinance returns the same article under every related ticker, so a
    multi-symbol run collects one copy per symbol; un-merged copies
    double-count in score_news's mean and crowd the LLM's 5-headline
    window. The first copy wins and absorbs later copies' related_symbols
    so cross-symbol attribution survives the merge.
    """
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for article in articles:
        key = article.get("link") or article.get("title")
        if not key:
            continue  # no link and no title: nothing to attribute or score
        if key not in merged:
            merged[key] = {**article}
            order.append(key)
        else:
            kept = merged[key]
            related = list(kept.get("related_symbols") or [])
            for sym in article.get("related_symbols") or []:
                if sym not in related:
                    related.append(sym)
            kept["related_symbols"] = related
    return [merged[key] for key in order]


def _sync_fetch_akshare_spot_table(ak):
    """Fetch the full A-share spot table — ONE network round-trip per run.

    The East Money spot table covers the entire A-share market (~5000
    rows), so it must be fetched once in the agent and sliced per symbol;
    fetching it per symbol re-downloads the whole market N times.
    """
    return ak.stock_zh_a_spot_em()


def _sync_fetch_akshare_stock_info(symbol: str, spot_df) -> dict[str, Any] | None:
    """Slice one symbol's row out of the pre-fetched spot table."""
    if spot_df is None:
        return None

    stock_row = spot_df[spot_df["代码"] == symbol]

    if stock_row.empty:
        return None

    row = stock_row.iloc[0]
    return {
        "symbol": symbol,
        "current_price": row.get("最新价"),
        "change": row.get("涨跌额", 0),
        "change_percent": row.get("涨跌幅", 0),
        "volume": row.get("成交量"),
        "amount": row.get("成交额"),
        "amplitude": row.get("振幅"),
        "high": row.get("最高"),
        "low": row.get("最低"),
        "open": row.get("今开"),
        "previous_close": row.get("昨收"),
        "timestamp": datetime.now().isoformat(),
    }


def _sync_fetch_akshare_financials(symbol: str, ak) -> dict[str, Any] | None:
    """Synchronous AkShare financials fetch — runs in thread pool."""
    df = ak.stock_financial_analysis_indicator(symbol=symbol)

    if df.empty:
        return None

    latest = df.iloc[-1]
    return {
        "symbol": symbol,
        "metrics": {
            "roe": latest.get("净资产收益率"),
            "roa": latest.get("总资产净利率"),
            "gross_margin": latest.get("销售毛利率"),
            "net_margin": latest.get("销售净利率"),
            "debt_to_asset": latest.get("资产负债率"),
            "current_ratio": latest.get("流动比率"),
            "quick_ratio": latest.get("速动比率"),
        },
        "timestamp": datetime.now().isoformat(),
    }


def _sync_fetch_akshare_history(symbol: str, ak) -> dict[str, Any] | None:
    """Fetch A-share daily bars (qfq-adjusted) in the yfinance-compatible shape.

    Without bars the technical agent has nothing to compute on — CN symbols
    degraded to spot-only. Same keys as `_historical_data_to_dict` so every
    downstream consumer is source-agnostic.
    """
    start = (datetime.now() - timedelta(days=DEFAULT_HISTORY_DAYS)).strftime("%Y%m%d")
    end = datetime.now().strftime("%Y%m%d")
    df = ak.stock_zh_a_hist(
        symbol=symbol, period="daily", start_date=start, end_date=end, adjust="qfq"
    )

    if df is None or df.empty:
        return None

    return {
        "dates": [d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d) for d in df["日期"]],
        "open": df["开盘"].tolist(),
        "high": df["最高"].tolist(),
        "low": df["最低"].tolist(),
        "close": df["收盘"].tolist(),
        "volume": df["成交量"].tolist(),
    }


class DataCollectionAgent(BaseAgent):
    """Agent responsible for collecting stock market data.

    This agent:
    - Fetches real-time and historical price data
    - Collects financial data (income statement, balance sheet, cash flow)
    - Gathers news and sentiment data
    - Normalizes and cleans data from multiple sources

    Data sources:
    - yfinance: Free source for US and international stocks
    - AkShare: Can be added for Chinese market data
    """

    async def execute(self, state: AgentState) -> dict[str, Any]:
        """Execute the data collection agent.

        Args:
            state: Current agent state

        Returns:
            Partial state with collected data
        """
        symbols = state.get("symbols", [])
        if not symbols:
            logger.warning("No symbols provided for data collection")
            return {"market_data": {}, "financial_data": {}, "news_data": []}

        logger.info(f"Collecting data for {len(symbols)} symbols: {symbols}")

        # Collect data concurrently for all symbols
        tasks = [self._collect_symbol_data(symbol) for symbol in symbols]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        market_data = {}
        financial_data = {}
        news_data = []

        for symbol, result in zip(symbols, results):
            if isinstance(result, Exception):
                logger.error(f"Failed to collect data for {symbol}: {result}")
                continue

            if result:
                market_data[symbol] = result.get("market_data", {})
                financial_data[symbol] = result.get("financial_data", {})
                news_data.extend(result.get("news_data", []))

        # Merge duplicate articles (same link/title) across symbol fetches
        news_data = _dedup_news(news_data)

        # One benchmark series per represented market (max two extra
        # round-trips per run) so the risk stage can regress beta/alpha/R².
        # A failed fetch just leaves the key absent — beta degrades exactly
        # as it did before benchmarks existed.
        tickers = sorted({_benchmark_ticker_for(s) for s in symbols})
        fetched = await asyncio.gather(*(self._fetch_benchmark_history(t) for t in tickers))
        benchmarks = dict(zip(tickers, fetched))
        for symbol, data in market_data.items():
            bench = benchmarks.get(_benchmark_ticker_for(symbol))
            if bench and data:
                market_data[symbol]["benchmark_historical_data"] = bench

        logger.info(
            f"Collected data for {len(market_data)} symbols, " f"{len(news_data)} news items"
        )

        # Return only the partial state (fields we modify)
        return {
            "market_data": market_data,
            "financial_data": financial_data,
            "news_data": news_data[-100:],  # Keep last 100 unique news items
        }

    async def _collect_symbol_data(self, symbol: str) -> dict[str, Any]:
        """Collect all data for a single symbol.

        Args:
            symbol: Stock symbol

        Returns:
            Dictionary containing market_data, financial_data, news_data
        """
        try:
            # Collect market data
            market_data = await self._fetch_market_data(symbol)

            # Collect financial data
            financial_data = await self._fetch_financial_data(symbol)

            # Collect news
            news_data = await self._fetch_news(symbol)

            return {
                "market_data": market_data,
                "financial_data": financial_data,
                "news_data": news_data,
            }

        except Exception as e:
            logger.error(f"Error collecting data for {symbol}: {e}")
            raise

    async def _fetch_market_data(self, symbol: str) -> dict[str, Any]:
        """Fetch market data for a symbol.

        Primary path is the direct yfinance snapshot; when it yields nothing
        (rate limits, delisted mapping), fall back to the shared multi-source
        provider chain (yfinance -> finnhub -> akshare -> yahoo-api) that the
        ReAct tools use, so both paths share the same resilience.

        Args:
            symbol: Stock symbol

        Returns:
            Dictionary containing price data and statistics
        """
        try:
            yahoo_symbol = convert_to_yahoo_symbol(symbol)
            logger.info(f"Fetching market data for {symbol} (Yahoo: {yahoo_symbol})")

            async with _yfinance_semaphore:
                result = await asyncio.to_thread(
                    _sync_fetch_market_data, yahoo_symbol, symbol, self._historical_data_to_dict
                )

            if not result or not result.get("historical_data"):
                fallback = await fetch_stock_data(symbol)
                market = (fallback or {}).get("market_data", {}).get(symbol) or {}
                if market.get("historical_data"):
                    logger.info(
                        f"[data_agent] provider-chain fallback supplied market data for {symbol}"
                    )
                    return {**market, "symbol": symbol}

            return result

        except Exception as e:
            logger.error(f"Error fetching market data for {symbol}: {e}")
            return {}

    async def _fetch_benchmark_history(self, yahoo_symbol: str) -> dict[str, Any] | None:
        """Benchmark history via the shared yfinance semaphore; None on failure."""
        try:
            async with _yfinance_semaphore:
                return await asyncio.to_thread(_sync_fetch_benchmark_history, yahoo_symbol)
        except Exception as e:
            logger.warning(f"Benchmark history unavailable for {yahoo_symbol}: {e}")
            return None

    async def _fetch_financial_data(self, symbol: str) -> dict[str, Any]:
        """Fetch financial data for a symbol.

        Args:
            symbol: Stock symbol

        Returns:
            Dictionary containing financial metrics
        """
        try:
            yahoo_symbol = convert_to_yahoo_symbol(symbol)

            async with _yfinance_semaphore:
                result = await asyncio.to_thread(
                    _sync_fetch_financial_data,
                    yahoo_symbol,
                    symbol,
                    self._financial_statement_to_dict,
                )
            return result

        except Exception as e:
            logger.error(f"Error fetching financial data for {symbol}: {e}")
            return {}

    async def _fetch_news(self, symbol: str) -> list[dict[str, Any]]:
        """Fetch news for a symbol.

        Args:
            symbol: Stock symbol

        Returns:
            List of news articles
        """
        try:
            yahoo_symbol = convert_to_yahoo_symbol(symbol)

            async with _yfinance_semaphore:
                articles = await asyncio.to_thread(_sync_fetch_news, yahoo_symbol, symbol)

            logger.info(f"Fetched {len(articles)} news articles for {symbol}")
            return articles

        except Exception as e:
            logger.error(f"Error fetching news for {symbol}: {e}")
            return []

    def _historical_data_to_dict(self, df: pd.DataFrame) -> dict[str, Any]:
        """Convert historical price DataFrame to dictionary.

        Args:
            df: Historical price DataFrame

        Returns:
            Dictionary with price data
        """
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

    def _financial_statement_to_dict(self, df: pd.DataFrame) -> dict[str, Any]:
        """Convert financial statement DataFrame to dictionary.

        Args:
            df: Financial statement DataFrame

        Returns:
            Dictionary with financial data, stamped with per-period visibility
            dates (period end + reporting lag) so backtests cannot peek at
            statements before they were filed.
        """
        if df is None or df.empty:
            return {}

        from app.backtest import stamp_visibility

        return stamp_visibility(
            {
                "dates": [d.strftime("%Y-%m-%d") for d in df.columns],
                "data": {row: df.loc[row].tolist() for row in df.index},
            }
        )


class AkShareDataAgent(BaseAgent):
    """Agent for collecting Chinese stock data using AkShare.

    This is an alternative data source for Chinese A-shares.
    AkShare provides comprehensive Chinese market data for free.
    """

    async def execute(self, state: AgentState) -> dict[str, Any]:
        """Execute the AkShare data collection agent.

        Args:
            state: Current agent state

        Returns:
            Partial state with collected data
        """
        symbols = state.get("symbols", [])

        # Filter for Chinese symbols (6 digits)
        cn_symbols = [s for s in symbols if s.isdigit() and len(s) == 6]

        if not cn_symbols:
            logger.info("No Chinese symbols found, skipping AkShare collection")
            return {"market_data": {}, "financial_data": {}}

        logger.info(f"Collecting Chinese stock data for {len(cn_symbols)} symbols")

        try:
            import akshare as ak
        except ImportError:
            logger.warning("AkShare not installed, skipping Chinese stock data")
            return {"market_data": {}, "financial_data": {}}

        market_data = {}
        financial_data = {}

        # One spot-table round-trip for ALL symbols; slices are local.
        spot_df = await self._fetch_akshare_spot_table(ak)

        async def _collect(symbol: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
            """Per-symbol history + financials; both degrade to None alone."""
            stock_info = await self._fetch_akshare_stock_info(symbol, spot_df)
            if stock_info:
                # Daily bars unlock full technical analysis; without them
                # the symbol degrades to spot-only (still a valid report).
                history = await self._fetch_akshare_history(symbol, ak)
                if history:
                    stock_info["historical_data"] = history
                    stock_info["as_of"] = history["dates"][-1]

            financials = await self._fetch_akshare_financials(symbol, ak)
            return stock_info, financials

        # Per-symbol work runs concurrently (bounded by _akshare_semaphore);
        # gather preserves cn_symbols order for deterministic output.
        collected = await asyncio.gather(*(_collect(s) for s in cn_symbols))
        for symbol, (stock_info, stock_financials) in zip(cn_symbols, collected):
            if stock_info:
                market_data[symbol] = stock_info
            if stock_financials:
                financial_data[symbol] = stock_financials

        logger.info(f"Collected AkShare data for {len(market_data)} symbols")

        # Return only the partial state (fields we modify)
        return {
            "market_data": market_data,
            "financial_data": financial_data,
        }

    async def _fetch_akshare_spot_table(self, ak):
        """Fetch the shared spot table; None when the source is unreachable."""
        try:
            async with _akshare_semaphore:
                return await asyncio.to_thread(_sync_fetch_akshare_spot_table, ak)
        except Exception as e:
            logger.error(f"Error fetching AkShare spot table: {e}")
            return None

    async def _fetch_akshare_stock_info(self, symbol: str, spot_df) -> dict[str, Any] | None:
        """Slice one symbol's market row out of the pre-fetched spot table.

        Args:
            symbol: Stock symbol (6 digits)
            spot_df: Full A-share spot table (or None when fetch failed)

        Returns:
            Dictionary containing stock data
        """
        try:
            async with _akshare_semaphore:
                return await asyncio.to_thread(_sync_fetch_akshare_stock_info, symbol, spot_df)
        except Exception as e:
            logger.error(f"Error fetching AkShare data for {symbol}: {e}")
            return None

    async def _fetch_akshare_financials(self, symbol: str, ak) -> dict[str, Any] | None:
        """Fetch Chinese stock financials using AkShare.

        Args:
            symbol: Stock symbol (6 digits)
            ak: AkShare module

        Returns:
            Dictionary containing financial data
        """
        try:
            async with _akshare_semaphore:
                return await asyncio.to_thread(_sync_fetch_akshare_financials, symbol, ak)
        except Exception as e:
            logger.error(f"Error fetching AkShare financials for {symbol}: {e}")
            return None

    async def _fetch_akshare_history(self, symbol: str, ak) -> dict[str, Any] | None:
        """Fetch Chinese stock daily bars using AkShare.

        Args:
            symbol: Stock symbol (6 digits)
            ak: AkShare module

        Returns:
            Historical data dict (yfinance-compatible), or None on failure
        """
        try:
            async with _akshare_semaphore:
                return await asyncio.to_thread(_sync_fetch_akshare_history, symbol, ak)
        except Exception as e:
            logger.error(f"Error fetching AkShare history for {symbol}: {e}")
            return None
