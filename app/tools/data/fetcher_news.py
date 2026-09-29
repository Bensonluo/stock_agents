"""News feeds (East Money CN, yfinance, Finnhub) and the article /
earnings-record mappers. Split from fetcher.py (behavior-preserving);
outside callers keep importing from fetcher.py."""

import math
from typing import Any

import pandas as pd

from app.tools.data.fetcher_common import _cache_get, _cache_set
from app.utils.logging import get_logger

logger = get_logger(__name__)

# News goes stale faster than benchmarks: within one analysis run the cache
# dedups the ReAct path's per-tool refetches, but a fresh user query ten
# minutes later should see new headlines.
_CN_NEWS_CACHE_TTL = 600


def fetch_cn_news(symbol: str) -> list[dict[str, Any]] | None:
    """East Money per-stock news for an A-share (akshare ``stock_news_em``).

    yfinance covers A-share symbols sparsely and in English; this is the
    native Chinese feed. Same article shape the pipeline's yfinance path
    emits so dedup/scoring consume both without branching. Returns None on
    any failure so the caller keeps whatever the primary fetch produced.

    Successful fetches are cached for ten minutes: every ReAct analysis
    tool re-enters _fetch_and_split for the same symbol, so one run would
    otherwise download this feed several times over. Failures are never
    cached — the next call retries the source.
    """
    key = f"cn_news_{symbol}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    try:
        import akshare as ak
    except ImportError:
        return None
    try:
        df = ak.stock_news_em(symbol=symbol)
    except Exception as e:
        logger.warning(f"[akshare] CN news failed for {symbol}: {e}")
        return None
    if df is None or df.empty or "新闻标题" not in df.columns:
        return None

    articles: list[dict[str, Any]] = []
    for _, row in df.head(20).iterrows():
        title = str(row.get("新闻标题") or "").strip()
        if not title:
            continue
        content = str(row.get("新闻内容") or "").strip()
        articles.append(
            {
                "title": title,
                "link": str(row.get("新闻链接") or "").strip() or None,
                "published": str(row.get("发布时间") or "").strip() or None,
                "source": str(row.get("文章来源") or "").strip() or None,
                "summary": content[:300] if content else None,
                "related_symbols": [symbol],
                "original_symbol": symbol,
            }
        )
    result = articles or None
    if result is not None:
        _cache_set(key, result, ttl=_CN_NEWS_CACHE_TTL)
    return result


def dedup_news(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge duplicate articles (same link, else title) across feeds/symbols.

    yfinance returns the same article under every related ticker, and East
    Money syndicates wire stories yfinance also carries, so multi-source
    fetches collect one copy per source; un-merged copies double-count in
    score_news's mean and crowd the LLM's 5-headline window. The first copy
    wins and absorbs later copies' related_symbols so cross-symbol
    attribution survives the merge. Shared by the pipeline's execute() and
    the ReAct tools' fetch seam.
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


def yfinance_news_articles(items: list[dict[str, Any]], symbol: str) -> list[dict[str, Any]]:
    """Map raw yfinance news items to the canonical article shape.

    The pipeline's ``_sync_fetch_news`` and the fetcher's yfinance provider
    consume the same raw items; the canonical keys (link/published/
    related_symbols) are what recency decay and dedup read. Title-less
    items are dropped — there is nothing to score or attribute.
    """
    articles: list[dict[str, Any]] = []
    for item in items:
        content = item.get("content", {})
        title = content.get("title") or item.get("title")
        if not title:
            continue
        link = None
        if content.get("canonicalUrl"):
            link = content["canonicalUrl"].get("url")
        if not link and item.get("link"):
            link = item.get("link")
        provider = content.get("provider", {})
        related = list(item.get("relatedTickers") or [])
        if symbol not in related:
            related.append(symbol)
        articles.append(
            {
                "title": title,
                "link": link,
                "published": content.get("pubDate") or item.get("providerPublishTime"),
                "source": provider.get("displayName") or item.get("publisher"),
                "summary": content.get("summary") or item.get("summary"),
                "related_symbols": related,
                "original_symbol": symbol,
            }
        )
    return articles


def finnhub_news_articles(
    items: list[dict[str, Any]], *, symbol: str | None = None
) -> list[dict[str, Any]]:
    """Map Finnhub /company-news items to the canonical article shape.

    Finnhub's raw keys (headline/url/datetime) are renamed to the canonical
    ones so recency decay (parse_published reads epoch ints) and dedup (link
    key) work without provider-specific branching downstream.

    ``symbol`` stamps the queried symbol onto every article
    (``original_symbol`` + ``related_symbols``): the feed is per-company, so
    attribution is a fact of the request. Sentiment's per-symbol matching
    keys off those fields — unattributed fallback news starves every symbol
    but the first (review 2026-09-26, P2#7).
    """
    articles: list[dict[str, Any]] = []
    for item in items:
        title = item.get("headline")
        if not title:
            continue
        article: dict[str, Any] = {
            "title": title,
            "link": item.get("url"),
            "published": item.get("datetime"),
            "source": item.get("source"),
            "summary": item.get("summary"),
        }
        if symbol:
            article["original_symbol"] = symbol
            article["related_symbols"] = [symbol]
        articles.append(article)
    return articles


# yfinance's earnings_dates columns, mapped to the canonical record keys.
_EARNINGS_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "eps_estimate": ("EPS Estimate", "EPS estimate", "epsEstimate"),
    "eps_actual": ("Reported EPS", "Surprise EPS"),
    "surprise_pct": ("Surprise(%)", "Surprise Pct"),
}


def _earnings_value(value: Any) -> float | None:
    """A finite float or None — NaN/None must not leak into JSON payloads."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def earnings_records(frame: Any) -> list[dict[str, Any]]:
    """yfinance ``ticker.earnings_dates`` frame → canonical records.

    ``to_dict("records")`` on this frame drops the DatetimeIndex entirely —
    the date is the only column that matters downstream (the next-earnings
    window), so the conversion here resets the index first and keeps each
    date as an ISO string. Value columns map through the alias table; a
    missing column simply omits its key. None/empty frames give ``[]``.
    """
    if frame is None or getattr(frame, "empty", False):
        return []
    try:
        records: list[dict[str, Any]] = []
        columns = {str(name) for name in frame.columns}
        for index, row in frame.iterrows():
            try:
                day = pd.Timestamp(index).date().isoformat()
            except (TypeError, ValueError):
                continue
            record: dict[str, Any] = {"date": day}
            for key, aliases in _EARNINGS_COLUMN_ALIASES.items():
                for alias in aliases:
                    if alias in columns:
                        record[key] = _earnings_value(row[alias])
                        break
            records.append(record)
        return records
    except Exception:
        return []
