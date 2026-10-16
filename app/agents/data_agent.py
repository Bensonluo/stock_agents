"""Data collection agent for fetching stock market data."""

import asyncio
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import yfinance as yf

from app.agents.base import BaseAgent
from app.config import get_settings
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
# Benchmark indices come from the same seam so pipeline and ReAct tools
# share ONE cached implementation.
# Shared CN financial mapping lives in the fetcher seam too (the ReAct
# provider chain emits the same metrics); the three pure re-exports
# (F401-suppressed) keep this module the single import point for the
# agent's call sites and its existing tests.
from app.tools.data.consensus import (  # noqa: E402
    fetch_cn_consensus,
    fetch_us_consensus,
    info_consensus_annotation,
)
from app.tools.data.fetcher import (  # noqa: E402
    BENCHMARK_TICKERS,
    DEFAULT_HISTORY_DAYS,
    _debt_to_equity_from_asset_ratio,  # noqa: F401
    _indicator_value,  # noqa: F401
    _pct_to_ratio,  # noqa: F401
    _sync_fetch_akshare_financials,
    _sync_fetch_tencent_cn_hist,
    benchmark_ticker_for,
    build_event_calendar,
    earnings_records,
    earnings_surprise_summary,
    fetch_benchmark_history,
    fetch_cn_news,
    fetch_cn_sector_benchmark,
    fetch_stock_data,
    fetch_us_news,
    sector_benchmark_ticker,
)
from app.tools.data.fetcher import dedup_news as _dedup_news  # noqa: E402
from app.tools.data.option_signals import (  # noqa: E402
    fetch_qvix_context,
    fetch_sse_option_snapshot,
)
from app.tools.data.provider_health import record_provider_outcome  # noqa: E402
from app.tools.data.qvix_store import get_qvix_store  # noqa: E402
from app.tools.data.tencent_spot import tencent_cn_spot_table  # noqa: E402


def _yfinance_debt_to_equity_ratio(value: Any) -> float | None:
    """Convert yfinance's percentage-valued debtToEquity to a decimal ratio."""
    if value is None:
        return None
    return float(value) / 100.0


async def _no_option_snapshot() -> None:
    """Stand-in awaitable so the disabled option leg joins the tail gather."""
    return None


async def _no_consensus_blocks() -> list[None]:
    """Stand-in awaitable so the disabled consensus leg joins the tail gather."""
    return []


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

    # to_dict("records") drops the DatetimeIndex — the date is the one
    # column the event window needs; earnings_records keeps it.
    earnings_dates = earnings_records(ticker.earnings_dates)

    # Zero-network analyst depth: the same wholesale `info` payload already
    # carries Yahoo's aggregated analyst targets — mapping them into the
    # consensus block shape costs no round-trip. Non-CN symbols only: 6-digit
    # A-shares get the richer THS/Sina block from the tail gather below, so
    # the info draft is never even built for them (CN precedence is made
    # structural by the same benchmark_ticker_for split the gather uses,
    # not left to a merge rule). Toggle off → the whole consensus layer
    # stays dark, draft included.
    info_consensus = None
    if get_settings().consensus_enabled and benchmark_ticker_for(symbol) != BENCHMARK_TICKERS["cn"]:
        info_consensus = info_consensus_annotation(info)

    result = {
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
    # EPS surprise history rides the already-downloaded frame — a compact
    # summary beside the raw records; absence (nothing has reported yet)
    # omits the key entirely. And the info draft attaches only when it has
    # content, so rate-limited info degrades to the key-absent convention.
    surprise_summary = earnings_surprise_summary(earnings_dates)
    if surprise_summary is not None:
        result["earnings_surprise"] = surprise_summary
    if info_consensus is not None:
        result["consensus"] = info_consensus
    # Upcoming event calendar (pure annotation, report-layer contract):
    # US/HK ride the ticker this function already constructed — calendar/
    # dividends/splits are three reads off the same session, so a calendar
    # that rate-limits degrades to key-absent exactly like `info` above.
    # 6-digit CN symbols take the akshare seam from the async wrapper
    # (_fetch_financial_data) under the akshare semaphore — nothing
    # CN-networked happens inside this yfinance leg.
    if get_settings().events_enabled and benchmark_ticker_for(symbol) != BENCHMARK_TICKERS["cn"]:
        events = build_event_calendar(symbol, ticker=ticker)
        if events is not None:
            result["event_calendar"] = events
    # Multi-period trend depth: the same ticker session already exposes the
    # three quarterly statements — annual-only frames can't show inflection
    # points inside the year. getattr keeps a stripped/older ticker at key
    # absence; the statements flow through the SAME converter, so quarterly
    # visibility stamps (backtest point-in-time safety) come for free.
    if get_settings().trend_depth_enabled:
        q_income = getattr(ticker, "quarterly_income_stmt", None)
        q_balance = getattr(ticker, "quarterly_balance_sheet", None)
        q_cash = getattr(ticker, "quarterly_cashflow", None)
        if q_income is not None or q_balance is not None or q_cash is not None:
            result["statements_quarterly"] = {
                "income_statement": stmt_converter(q_income) if q_income is not None else {},
                "balance_sheet": stmt_converter(q_balance) if q_balance is not None else {},
                "cash_flow": stmt_converter(q_cash) if q_cash is not None else {},
            }
    return result


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


def _sync_fetch_akshare_history(symbol: str, ak) -> dict[str, Any] | None:
    """Fetch A-share daily bars (qfq-adjusted) in the yfinance-compatible shape.

    Without bars the technical agent has nothing to compute on — CN symbols
    degraded to spot-only. Same keys as `_historical_data_to_dict` so every
    downstream consumer is source-agnostic. East Money first; when
    push2his.eastmoney.com is unreachable (domain-blocked from the
    production CN host since 2026-09-27) the Tencent kline fallback serves
    the same window through the same mapping below.
    """
    start = (datetime.now() - timedelta(days=DEFAULT_HISTORY_DAYS)).strftime("%Y%m%d")
    end = datetime.now().strftime("%Y%m%d")
    df = None
    try:
        df = ak.stock_zh_a_hist(
            symbol=symbol, period="daily", start_date=start, end_date=end, adjust="qfq"
        )
    except Exception as e:
        logger.warning(f"AkShare East Money history failed for {symbol}: {e}")
    if df is None or df.empty:
        df = _sync_fetch_tencent_cn_hist(symbol, ak, DEFAULT_HISTORY_DAYS)

    if df is None or df.empty:
        return None

    history = {
        "dates": [d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d) for d in df["日期"]],
        "open": df["开盘"].tolist(),
        "high": df["最高"].tolist(),
        "low": df["最低"].tolist(),
        "close": df["收盘"].tolist(),
        "volume": df["成交量"].tolist(),
    }
    # Exact daily turnover in yuan — the liquidity layer's preferred input.
    # East Money's volume column is in 手 (100-share lots), so close×volume
    # would understate CN turnover by two orders of magnitude; 成交额 has no
    # such ambiguity. Key omitted entirely when the source lacks the column.
    if "成交额" in df.columns:
        history["amount"] = df["成交额"].tolist()
    return history


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

        # The five tail fetches — per-market benchmark series (one per
        # represented market, feeding the risk stage's beta/alpha/R²
        # regression), SPDR sector benchmarks, CN industry benchmarks, the
        # CN option snapshot (SSE per-contract IV/Greeks + volume PCR +
        # QVIX, iteration 155: market-level PURE ANNOTATION, the risk stage
        # labels 恐慌/中性/自满 and nothing scores it) and the analyst
        # consensus (iteration 163 CN: THS EPS forecasts + Sina ratings;
        # iteration 167 US: Finnhub ratings-only — dispatched by market,
        # both under financial_data[symbol]["consensus"], equally pure) —
        # read only
        # `symbols` and the already-collected `market_data`, never each
        # other's results, so they run in ONE gather: worst-case wall time
        # is the slowest leg, not the sum. Writes stay disjoint: the market
        # loop owns benchmark_historical_data; the SPDR sector map excludes
        # CN symbols so the CN industry loop keeps its unconditional write
        # of sector_benchmark_historical_data (CN blocks carry no sector
        # field today — the exclusion makes that guarantee structural, not
        # incidental); a failed fetch on any leg just leaves its key
        # absent, exactly as before the gather existed.
        cn_symbols = [s for s in market_data if benchmark_ticker_for(s) == BENCHMARK_TICKERS["cn"]]
        # Non-CN symbols (US + HK) take the ratings-only US consensus seam;
        # HK listings get an empty Finnhub answer, which caches and yields
        # no block — graceful, like any uncovered symbol.
        us_symbols = [s for s in market_data if benchmark_ticker_for(s) != BENCHMARK_TICKERS["cn"]]
        tickers = sorted({benchmark_ticker_for(s) for s in symbols})
        sector_tickers = {
            s: sector_benchmark_ticker((data or {}).get("sector"))
            for s, data in market_data.items()
            if benchmark_ticker_for(s) != BENCHMARK_TICKERS["cn"]
        }
        wanted = sorted({t for t in sector_tickers.values() if t})
        want_options = bool(get_settings().option_signals_enabled and cn_symbols)
        want_consensus = bool(get_settings().consensus_enabled and (cn_symbols or us_symbols))
        fetched, sector_fetched, cn_benchmarks, option_snapshot, consensus_blocks = (
            await asyncio.gather(
                asyncio.gather(*(fetch_benchmark_history(t) for t in tickers)),
                asyncio.gather(*(fetch_benchmark_history(t) for t in wanted)),
                asyncio.gather(*(fetch_cn_sector_benchmark(s) for s in cn_symbols)),
                self._fetch_option_snapshot() if want_options else _no_option_snapshot(),
                (
                    asyncio.gather(
                        *(
                            fetch_cn_consensus(s, (market_data.get(s) or {}).get("current_price"))
                            for s in cn_symbols
                        ),
                        *(fetch_us_consensus(s) for s in us_symbols),
                    )
                    if want_consensus
                    else _no_consensus_blocks()
                ),
            )
        )

        # One benchmark series per represented market (max two extra
        # round-trips per run) so the risk stage can regress beta/alpha/R².
        # A failed fetch just leaves the key absent — beta degrades exactly
        # as it did before benchmarks existed.
        benchmarks = dict(zip(tickers, fetched))
        for symbol, data in market_data.items():
            bench = benchmarks.get(benchmark_ticker_for(symbol))
            if bench and data:
                market_data[symbol]["benchmark_historical_data"] = bench

        # Sector-relative annotation: one extra series per mapped sector
        # (11 SPDR ETFs cover yfinance's sector vocabulary, shared 30-min
        # cache dedups across runs). CN names are excluded from the map —
        # they get the industry benchmark below; unmapped or failed
        # fetches leave the key absent exactly like the market benchmark.
        sector_benchmarks = dict(zip(wanted, sector_fetched))
        for symbol, ticker in sector_tickers.items():
            bench = sector_benchmarks.get(ticker) if ticker else None
            if bench and market_data[symbol]:
                market_data[symbol]["sector_benchmark_historical_data"] = bench

        # CN industry benchmark: SPDR ETFs don't cover Chinese sector names,
        # so A-shares get the East Money industry-board index instead — same
        # dates/close shape the sector regression consumes. Failure leaves
        # the key absent, exactly like the market benchmark above.
        for s, bench in zip(cn_symbols, cn_benchmarks):
            if bench and market_data[s]:
                market_data[s]["sector_benchmark_historical_data"] = bench

        # Analyst consensus (market-dispatched): rides the same
        # financial_data map the AkShare merge fills (per-key merge keeps
        # the consensus sibling alive); a None block (no coverage / total
        # fetch failure) leaves the key absent — the option/benchmark
        # absence convention. CN generators run before US in the gather, so
        # the zip order matches [*cn_symbols, *us_symbols].
        #
        # Non-CN symbols may already carry the zero-network info draft the
        # financial leg staged: the fetched block wins per sub-block (its
        # Finnhub band counts are the richer record) while the draft's
        # target_price fills the ratings-only gap, and hard-number evidence
        # upgrades the status — the CN seam's own "ok needs targets" rule.
        # CN symbols never get a draft (the sync leg's benchmark_ticker_for
        # split), so the fetched THS/Sina block always lands untouched —
        # CN precedence is structural, not a merge tie-break.
        for s, block in zip([*cn_symbols, *us_symbols], consensus_blocks):
            if block is None:
                continue
            current = financial_data.get(s) or {}
            draft = current.get("consensus")
            if s not in cn_symbols and isinstance(draft, dict):
                block = {**draft, **block}
                if block.get("target_price") is not None:
                    block["status"] = "ok"
            financial_data[s] = {**current, "consensus": block}

        logger.info(
            f"Collected data for {len(market_data)} symbols, " f"{len(news_data)} news items"
        )

        # Return only the partial state (fields we modify)
        result: dict[str, Any] = {
            "market_data": market_data,
            "financial_data": financial_data,
            "news_data": news_data[-100:],  # Keep last 100 unique news items
        }
        if option_snapshot is not None:
            result["option_snapshot"] = option_snapshot
        return result

    async def _fetch_option_snapshot(self) -> dict[str, Any] | None:
        """SSE option snapshot + QVIX context merged into one annotation payload.

        Each seam degrades alone (snapshot None keeps QVIX; both None → the
        execute-level key stays absent) — the same never-fail convention as
        the benchmark fetches.
        """
        try:
            snapshot = await asyncio.to_thread(fetch_sse_option_snapshot)
            qvix = await asyncio.to_thread(fetch_qvix_context, get_qvix_store())
        except Exception as e:
            logger.warning(f"Options implied-signal fetch failed: {e}")
            return None
        if snapshot is None and qvix is None:
            return None
        merged = dict(snapshot) if snapshot else {}
        merged["qvix_context"] = qvix
        return merged

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
                # fetch_stock_data normalizes every provider (keyed or flat)
                # to the FLAT snapshot shape at its boundary — read the block
                # flat; market_data[symbol] is the state-level convention.
                market = (fallback or {}).get("market_data") or {}
                if market.get("historical_data"):
                    logger.info(
                        f"[data_agent] provider-chain fallback supplied market data for {symbol}"
                    )
                    return {**market, "symbol": symbol}

            return result

        except Exception as e:
            logger.error(f"Error fetching market data for {symbol}: {e}")
            return {}

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

            if not result or not result.get("metrics"):
                fallback = await fetch_stock_data(symbol)
                # Same flat boundary contract as the market leg: the
                # snapshot's financial_data IS the block — read it flat and
                # stamp the symbol, never symbol-key it.
                financials = (fallback or {}).get("financial_data") or {}
                if financials.get("metrics"):
                    logger.info(
                        f"[data_agent] provider-chain fallback supplied financial data "
                        f"for {symbol}"
                    )
                    result = {**financials, "symbol": symbol}

            # CN event calendar (业绩预告/解禁/分红送配): attached after the
            # fallback resolution so a provider-chain block — which carries
            # no events of its own — cannot drop it. The akshare calls run
            # under the akshare semaphore, the same loop-safe pattern as the
            # financials/history legs.
            if (
                result
                and get_settings().events_enabled
                and benchmark_ticker_for(symbol) == BENCHMARK_TICKERS["cn"]
            ):
                events = await self._fetch_cn_event_calendar(symbol)
                if events is not None:
                    result["event_calendar"] = events

            return result

        except Exception as e:
            logger.error(f"Error fetching financial data for {symbol}: {e}")
            return {}

    async def _fetch_cn_event_calendar(self, symbol: str) -> dict[str, Any] | None:
        """AkShare event-calendar seam for 6-digit symbols.

        Sync akshare calls stay loop-safe inside asyncio.to_thread under the
        akshare semaphore — the same pattern as the financials/history legs.
        None (providers dark / module missing) → the key stays absent.
        """

        def _cn() -> dict[str, Any] | None:
            try:
                import akshare as ak
            except ImportError:
                return None
            return build_event_calendar(symbol, akshare_module=ak)

        try:
            async with _akshare_semaphore:
                return await asyncio.to_thread(_cn)
        except Exception as e:
            logger.warning(f"[data_agent] CN event calendar failed for {symbol}: {e}")
            return None

    async def _fetch_news(self, symbol: str) -> list[dict[str, Any]]:
        """Fetch news for a symbol.

        A-shares (6-digit codes) additionally pull the East Money native
        feed — yfinance covers them sparsely and in English only. The
        execute-level dedup folds any cross-source overlap.

        Args:
            symbol: Stock symbol

        Returns:
            List of news articles
        """
        yahoo_symbol = convert_to_yahoo_symbol(symbol)
        articles: list[dict[str, Any]] = []
        try:
            async with _yfinance_semaphore:
                articles = await asyncio.to_thread(_sync_fetch_news, yahoo_symbol, symbol)
        except Exception as e:
            logger.error(f"Error fetching news for {symbol}: {e}")

        if symbol.isdigit() and len(symbol) == 6:
            try:
                cn_articles = await asyncio.to_thread(fetch_cn_news, symbol)
            except Exception as e:
                logger.warning(f"CN news feed failed for {symbol}: {e}")
                cn_articles = None
            if cn_articles:
                articles = articles + cn_articles

        if not articles:
            # Provider-chain news fallback (Finnhub): the yfinance-only path
            # leaves US symbols silent when Yahoo rate-limits — the
            # documented state of the Tencent Cloud deploy since 2026-09-25.
            # No-op without a FINNHUB_API_KEY.
            try:
                fallback_articles = await fetch_us_news(symbol)
            except Exception as e:
                logger.warning(f"News fallback failed for {symbol}: {e}")
                fallback_articles = []
            if fallback_articles:
                logger.info(
                    f"[data_agent] news fallback supplied {len(fallback_articles)} articles"
                )
                articles = fallback_articles

        if articles:
            logger.info(f"Fetched {len(articles)} news articles for {symbol}")
        return articles

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
        spot_df = await self._fetch_akshare_spot_table(ak, cn_symbols)

        async def _collect(symbol: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
            """Per-symbol history + financials; both degrade to None alone."""
            stock_info = await self._fetch_akshare_stock_info(symbol, spot_df)
            # Daily bars are fetched regardless of the spot outcome: they
            # unlock full technical analysis, and with both spot sources
            # dark the Tencent kline inside _fetch_akshare_history still
            # answers — the old spot-gates-history design made that
            # fallback unreachable and killed the whole A-share path.
            history = await self._fetch_akshare_history(symbol, ak)
            if history:
                if stock_info:
                    stock_info["historical_data"] = history
                    stock_info["as_of"] = history["dates"][-1]
                else:
                    # No spot row anywhere: derive a minimal quote from the
                    # closes — the same derivation the ReAct fetcher's
                    # _akshare_cn uses. All sources dead keeps stock_info
                    # None (the existing degradation).
                    closes = history.get("close") or []
                    current = closes[-1] if closes else None
                    prev = closes[-2] if len(closes) > 1 else None
                    stock_info = {
                        "symbol": symbol,
                        "current_price": current,
                        "previous_close": prev,
                        "change": current - prev if current and prev else None,
                        "change_percent": (
                            ((current - prev) / prev * 100) if current and prev else None
                        ),
                        "historical_data": history,
                        "as_of": history["dates"][-1],
                        "timestamp": datetime.now().isoformat(),
                    }

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

    async def _fetch_akshare_spot_table(self, ak, cn_symbols: list[str]):
        """Fetch the shared spot table; None when both sources are unreachable.

        East Money first (its table is the column contract everything
        downstream slices). When push2 is unreachable (RemoteDisconnected
        from the production CN host since 2026-09-28), Tencent's batch
        quote serves the same EM-shaped table — one GET for all symbols,
        so the single-round-trip design survives the fallback. EM healthy
        never touches Tencent.
        """
        em_error: str | None = None
        try:
            async with _akshare_semaphore:
                em_df = await asyncio.to_thread(_sync_fetch_akshare_spot_table, ak)
        except Exception as e:
            logger.error(f"Error fetching AkShare spot table: {e}")
            em_df = None
            em_error = f"{type(e).__name__}: {e}"
        if em_df is not None and not em_df.empty:
            record_provider_outcome("em-spot-table", "ok")
            return em_df
        record_provider_outcome("em-spot-table", "fail", em_error or "empty spot table")
        logger.info("[data_agent] EM spot table dead, falling back to Tencent quotes")
        tx_df = await asyncio.to_thread(tencent_cn_spot_table, cn_symbols)
        if tx_df is not None and not tx_df.empty:
            record_provider_outcome("tencent-spot", "ok")
        else:
            record_provider_outcome("tencent-spot", "fail", "no spot table")
        return tx_df

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
