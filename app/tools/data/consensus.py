"""Analyst-consensus annotation layer, dispatched by market.

CN twin (iteration 163) — two akshare endpoints (shapes verified live
2026-09-30, akshare 1.18.96):
    stock_profit_forecast_ths(symbol, indicator='预测年报每股收益')
        [年度, 预测机构数, 最小值, 均值, 最大值, 行业平均数]
    stock_institute_recommend_detail(symbol)
        [股票代码, 股票名称, 目标价, 最新评级, 评级机构, 分析师, 行业, 评级日期]

US twin (iteration 167) — Finnhub /stock/recommendation: monthly analyst
band snapshots (strongBuy/buy/hold/sell/strongSell); the latest period
wins (max period string — feed order is never trusted), bands map onto
the same canonical five-label scale. Ratings-only: the endpoint carries
no hard-number evidence and takes no price input, so a US block never
has eps_forecast/target_price and its status is always
"insufficient_data".

Layered like option_signals (iteration 155) — both twins:
    fetch layer  — never-raise seams, raw payloads only (lazy akshare
                   frames / the Finnhub items list via _finnhub_get)
    cache layer  — raw payloads under consensus_raw:{symbol} /
                   consensus_us_raw:{symbol}, 30-min TTL; total failure is never
                   cached (retried), an empty payload IS cached (no coverage is
                   a valid provider answer)
    pure layer   — consensus_annotation / us_consensus_annotation build the
                   blocks from raw payloads (the CN one plus the caller's price)
    health layer — record_provider_outcome per endpoint seam ("ths-forecast" /
                   "sina-ratings" / "finnhub-recommendation"), empty payload =
                   ok (data absence, not failure); keyless Finnhub never records
                   (iteration 104 convention)

The annotation is PURE: nothing in the scoring, risk or decision paths may
read it (the liquidity/sector_relative/option_implied convention). Caching
the RAW frames (price-independent) means the annotation is recomputed fresh
on every call, so implied_upside always tracks the caller's current price.
"""

from __future__ import annotations

import asyncio
import math
import statistics
from datetime import date, timedelta
from typing import Any

import pandas as pd

from app.config import get_settings
from app.tools.data.fetcher_common import _cache_get, _cache_set
from app.tools.data.fetcher_finnhub import _finnhub_get
from app.tools.data.provider_health import record_provider_outcome

# Ratings older than this are not observations — analysts re-rate, and a
# 2-year-old target price says nothing about today's consensus. 180 days is
# roughly two earnings seasons of coverage.
CONSENSUS_RATING_WINDOW_DAYS = 180

# A mean/median over fewer observations is noise dressed up as consensus.
MIN_TARGET_OBSERVATIONS = 3

# Canonical bullish→bearish scale. Order is load-bearing: max() keeps the
# first maximum, so a count tie resolves to the more bullish label.
_RATING_LABELS = ("买入", "增持", "中性", "减持", "卖出")

_RAW_CACHE_PREFIX = "consensus_raw:"
_US_CACHE_PREFIX = "consensus_us_raw:"

# Finnhub band keys (strongBuy..strongSell) onto the canonical scale.
# Order-preserving map; count ties ride _RATING_LABELS's bullish-first
# order, same as the CN _ratings_block.
_US_BAND_TO_LABEL = {
    "strongBuy": "买入",
    "buy": "增持",
    "hold": "中性",
    "sell": "减持",
    "strongSell": "卖出",
}


def _to_float(value: Any) -> float | None:
    """Finite native float or None — np.float64/nan/inf/garbage all handled.

    The JSON boundary never accepts numpy types, and NaN poisons every
    downstream round(); refuse them at the door.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _to_int(value: Any) -> int | None:
    number = _to_float(value)
    return None if number is None else int(number)


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _recent_rows(ratings_df: pd.DataFrame | None) -> list[dict[str, Any]]:
    """Rows whose 评级日期 parses and falls inside the rating window.

    Exactly window_days old is IN (the cutoff is inclusive), one day older
    is OUT; unparseable dates are excluded rather than guessed.
    """
    if ratings_df is None or ratings_df.empty:
        return []
    cutoff = date.today() - timedelta(days=CONSENSUS_RATING_WINDOW_DAYS)
    recent = []
    for row in ratings_df.to_dict("records"):
        parsed = _parse_date(row.get("评级日期"))
        if parsed is not None and parsed >= cutoff:
            recent.append(row)
    return recent


def _eps_forecast_block(forecast_df: pd.DataFrame | None) -> dict[str, Any] | None:
    """THS annual EPS consensus: nearest year always, next year when adjacent.

    year2 is strictly year1+1 — a gap year (2026+2028) is not a growth
    signal, it is missing coverage. implied_growth needs a positive base:
    growth over a zero/negative mean is numerically meaningless.
    """
    if forecast_df is None or forecast_df.empty:
        return None
    rows: list[tuple[int, float, int | None, float | None]] = []
    for row in forecast_df.to_dict("records"):
        year = _to_int(row.get("年度"))
        mean = _to_float(row.get("均值"))
        if year is None or mean is None:
            continue
        rows.append((year, mean, _to_int(row.get("预测机构数")), _to_float(row.get("行业平均数"))))
    if not rows:
        return None
    rows.sort(key=lambda r: r[0])
    year1, mean1, org1, ind1 = rows[0]
    block: dict[str, Any] = {
        "year1": year1,
        "eps_mean": round(mean1, 4),
        "org_count": org1,
        "industry_avg": round(ind1, 4) if ind1 is not None else None,
    }
    for year, mean, _org, _ind in rows[1:]:
        if year == year1 + 1:
            block["year2"] = year
            block["eps_mean_year2"] = round(mean, 4)
            if mean1 > 0:
                block["implied_growth"] = round(mean / mean1 - 1, 4)
            break
    return block


def _target_price_block(
    recent_rows: list[dict[str, Any]], current_price: Any
) -> dict[str, Any] | None:
    """Consensus target stats over the rating window; None below the floor.

    Non-positive and unparseable 目标价 values are not observations. The
    implied upside rides on the caller's price — the cache stores raw frames
    precisely so this stays fresh per call.
    """
    targets = []
    for row in recent_rows:
        value = _to_float(row.get("目标价"))
        if value is not None and value > 0:
            targets.append(value)
    if len(targets) < MIN_TARGET_OBSERVATIONS:
        return None
    mean = sum(targets) / len(targets)
    block: dict[str, Any] = {
        "count": len(targets),
        "mean": round(mean, 4),
        "median": round(float(statistics.median(targets)), 4),
        "window_days": CONSENSUS_RATING_WINDOW_DAYS,
    }
    price = _to_float(current_price)
    if price is not None and price > 0:
        block["implied_upside"] = round(mean / price - 1, 4)
    return block


def _ratings_block(recent_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Label counts over the canonical scale; off-scale labels are ignored.

    A feed with zero known-label rows yields no block — "only 推荐 ratings"
    is absence of consensus on this scale, not a neutral consensus.
    """
    counts = {label: 0 for label in _RATING_LABELS}
    total = 0
    for row in recent_rows:
        label = row.get("最新评级")
        if label in counts:
            counts[label] += 1
            total += 1
    if total < 1:
        return None
    dominant = max(_RATING_LABELS, key=lambda label: counts[label])
    return {"counts": counts, "dominant": dominant, "total": total}


def consensus_annotation(
    forecast_df: pd.DataFrame | None,
    ratings_df: pd.DataFrame | None,
    current_price: Any = None,
) -> dict[str, Any] | None:
    """Build the pure consensus block; None when no block has any content.

    status is "ok" when the hard-number evidence (EPS forecast or target
    prices) exists; a ratings-only block is "insufficient_data" — counts
    alone don't justify the stronger claim.
    """
    eps = _eps_forecast_block(forecast_df)
    recent_rows = _recent_rows(ratings_df)
    target = _target_price_block(recent_rows, current_price)
    ratings = _ratings_block(recent_rows)
    if eps is None and target is None and ratings is None:
        return None
    block: dict[str, Any] = {
        "status": "ok" if (eps is not None or target is not None) else "insufficient_data"
    }
    if eps is not None:
        block["eps_forecast"] = eps
    if target is not None:
        block["target_price"] = target
    if ratings is not None:
        block["ratings"] = ratings
    return block


def _sync_fetch_raw(symbol: str) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """Fetch both endpoints; each leg degrades alone, never raises.

    An empty frame is a provider "ok" (no coverage for this symbol); an
    exception is a "fail". Both legs dead → (None, None), which the async
    wrapper refuses to cache so the next call retries.
    """
    try:
        import akshare as ak
    except ImportError:
        return None, None

    forecast_df = None
    try:
        forecast_df = ak.stock_profit_forecast_ths(symbol=symbol, indicator="预测年报每股收益")
        record_provider_outcome("ths-forecast", "ok")
    except Exception as e:
        record_provider_outcome("ths-forecast", "fail", f"{type(e).__name__}: {e}")

    ratings_df = None
    try:
        ratings_df = ak.stock_institute_recommend_detail(symbol=symbol)
        record_provider_outcome("sina-ratings", "ok")
    except Exception as e:
        record_provider_outcome("sina-ratings", "fail", f"{type(e).__name__}: {e}")

    return forecast_df, ratings_df


async def fetch_cn_consensus(
    symbol: str, current_price: float | None = None
) -> dict[str, Any] | None:
    """Cached consensus annotation for a 6-digit CN symbol; never raises.

    Raw frames are cached for 30 minutes (price-independent); the annotation
    is recomputed on every call so implied_upside tracks the caller's price.
    """
    cache_key = f"{_RAW_CACHE_PREFIX}{symbol}"
    raw = _cache_get(cache_key)
    if raw is None:
        raw = await asyncio.to_thread(_sync_fetch_raw, symbol)
        forecast_df, ratings_df = raw
        if forecast_df is None and ratings_df is None:
            return None  # total failure — retried next call, never cached
        _cache_set(cache_key, raw)
    forecast_df, ratings_df = raw
    return consensus_annotation(forecast_df, ratings_df, current_price)


def us_consensus_annotation(items: Any) -> dict[str, Any] | None:
    """Ratings-only US block from Finnhub band snapshots; None when empty.

    The feed is a list of monthly snapshots — the max period string wins,
    never the feed order. Ratings-only evidence can't justify "ok", so a
    US block is always "insufficient_data" (the counts still render).
    """
    if not isinstance(items, list) or not items:
        return None
    rows = [r for r in items if isinstance(r, dict)]
    if not rows:
        return None
    latest = max(rows, key=lambda r: str(r.get("period") or ""))
    counts = {label: _to_int(latest.get(band)) or 0 for band, label in _US_BAND_TO_LABEL.items()}
    total = sum(counts.values())
    if total < 1:
        return None
    dominant = max(_RATING_LABELS, key=lambda label: counts[label])
    return {
        "status": "insufficient_data",
        "ratings": {"counts": counts, "dominant": dominant, "total": total},
    }


def _sync_fetch_us_raw(symbol: str) -> list[Any] | None:
    """Fetch the Finnhub recommendation snapshots; never raises.

    An empty list is a provider "ok" (no coverage for this symbol); None
    is a failure. Keyless is a configuration state, not a provider
    failure — the seam then returns None without recording (iteration
    104 convention: keyless layers never reach the health counters).
    """
    items = _finnhub_get("/stock/recommendation", {"symbol": symbol})
    if items is not None:
        record_provider_outcome("finnhub-recommendation", "ok")
    elif get_settings().finnhub_api_key:
        record_provider_outcome("finnhub-recommendation", "fail", "request failed or no data")
    return items


async def fetch_us_consensus(symbol: str) -> dict[str, Any] | None:
    """Cached US consensus annotation for a non-CN symbol; never raises.

    Raw snapshots are cached for 30 minutes; total failure (None) is
    retried on the next call, never cached. No price argument — the
    endpoint carries none, so there is no upside math to keep fresh.
    """
    cache_key = f"{_US_CACHE_PREFIX}{symbol}"
    raw = _cache_get(cache_key)
    if raw is None:
        raw = await asyncio.to_thread(_sync_fetch_us_raw, symbol)
        if raw is None:
            return None  # total failure — retried next call, never cached
        _cache_set(cache_key, raw)  # empty list IS cached (no coverage is a valid answer)
    return us_consensus_annotation(raw)


def _label_from_mean(mean: float) -> str:
    """Yahoo's 1-5 recommendationMean (1=strong buy … 5=strong sell) onto the
    canonical scale — same polarity, nearest label wins, clamped to the ends.
    """
    index = min(max(int(round(mean)) - 1, 0), len(_RATING_LABELS) - 1)
    return _RATING_LABELS[index]


def info_consensus_annotation(info: Any) -> dict[str, Any] | None:
    """Zero-network consensus block mapped from the yfinance ``ticker.info``
    payload the financial leg already downloads (audit 2026-09-30: Yahoo's
    aggregated analyst targets were inside every US/HK fetch and never
    surfaced). Third pure builder beside consensus_annotation / the Finnhub
    twin — same record shape, so consumers need no new schema:

        target_price — targetMeanPrice/targetMedianPrice/targetLowPrice/
                       targetHighPrice ride the CN block's keys (mean/median/
                       low/high); numberOfAnalystOpinions is ``count``. The
                       block needs a positive targetMeanPrice; the other
                       fields are emitted only when info actually carries
                       them. ``window_days`` is NOT emitted — the provider
                       snapshot has no rating-window semantics to borrow.
        ratings      — recommendationKey/recommendationMean + the analyst
                       count. The source carries no per-band counts, so
                       ``counts`` is the canonical five-key dict at zero
                       (no fabricated observations — dominant/mean/total
                       hold the real evidence); ``dominant`` is the
                       provider's own key string, bucketed from the 1-5
                       mean only when the key string is missing. ``mean``
                       (additive key) keeps the raw scalar.

    ``implied_upside`` follows the CN block: mean/target − 1 against the
    caller's price, falling back to info's own currentPrice (the market
    leg sources the same field). Status mirrors consensus_annotation:
    "ok" on hard-number evidence (targets), "insufficient_data" when only
    the recommendation summary exists. None when info has neither —
    missing/None/NaN fields and non-dict payloads degrade to absence.
    """
    if not isinstance(info, dict):
        return None

    target: dict[str, Any] | None = None
    mean = _to_float(info.get("targetMeanPrice"))
    if mean is not None and mean > 0:
        target = {}
        count = _to_int(info.get("numberOfAnalystOpinions"))
        if count is not None and count > 0:
            target["count"] = count
        target["mean"] = round(mean, 4)
        for key, raw in (
            ("median", info.get("targetMedianPrice")),
            ("low", info.get("targetLowPrice")),
            ("high", info.get("targetHighPrice")),
        ):
            value = _to_float(raw)
            if value is not None and value > 0:
                target[key] = round(value, 4)
        price = _to_float(info.get("currentPrice") or info.get("regularMarketPrice"))
        if price is not None and price > 0:
            target["implied_upside"] = round(mean / price - 1, 4)

    ratings: dict[str, Any] | None = None
    key = info.get("recommendationKey")
    has_key = isinstance(key, str) and bool(key)
    mean_rating = _to_float(info.get("recommendationMean"))
    if has_key or (mean_rating is not None and 0 < mean_rating <= 5):
        ratings = {"counts": {label: 0 for label in _RATING_LABELS}}
        if has_key:
            ratings["dominant"] = key
        elif mean_rating is not None:
            ratings["dominant"] = _label_from_mean(mean_rating)
        if mean_rating is not None:
            ratings["mean"] = round(mean_rating, 4)
        ratings["total"] = _to_int(info.get("numberOfAnalystOpinions")) or 0

    if target is None and ratings is None:
        return None
    block: dict[str, Any] = {"status": "ok" if target is not None else "insufficient_data"}
    if target is not None:
        block["target_price"] = target
    if ratings is not None:
        block["ratings"] = ratings
    return block
