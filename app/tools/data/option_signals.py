"""SSE options implied-signal layer (iteration 155).

China lists only ETF/index options — there is no per-stock option chain —
so this is a MARKET-LEVEL signal: the data agent attaches one
``option_snapshot`` per run (only when CN symbols are present) and the risk
agent turns it into one ``option_implied`` annotation block
(恐慌/中性/自满). PURE ANNOTATION: risk_score, weights, position sizing and
decisions must never read it.

Sources (akshare 1.18.96, signatures verified offline):
    option_risk_indicator_sse(date)  per-contract Greeks + IV (ratio)
    option_current_day_sse()         contract directory (strike/expiry/cp)
    option_daily_stats_sse(date)     official per-underlying volume PCR
    index_option_50etf_qvix()        QVIX index (third-party host → local store)

Layers:
    1. fetch_sse_option_snapshot / fetch_qvix_context — sync network seams
       (callers wrap in asyncio.to_thread); shared 30-min cache, provider-
       health outcomes, never raise. akshare is imported lazily inside the
       functions so tests can inject a fake module.
    2. compute_iv_metrics  — pure: ATM IV per expiry, term structure, skew.
    3. compute_pcr         — pure: per-underlying passthrough + market PCR.
    4. build_option_implied — pure: regime label from the QVIX percentile.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta
from typing import Any

from app.tools.data.fetcher_common import _cache_get, _cache_set
from app.tools.data.provider_health import record_provider_outcome
from app.utils.logging import get_logger

logger = get_logger(__name__)

_SNAPSHOT_CACHE_KEY = "option_snapshot"
_QVIX_CACHE_KEY = "qvix_context"
# Trade-date walkback budget for the risk-indicator endpoint: today minus
# weekends/holidays — six calendar tries covers a CN holiday bridge.
_TRADE_DATE_WALKBACK_TRIES = 6
_QVIX_WINDOW_DAYS = 252  # one trading year
_QVIX_MIN_ROWS = 30  # below this the percentile is noise, not evidence


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clean_number(value: Any) -> float | None:
    """float() with SSE's thousands commas stripped and NaN guard."""
    if value is None:
        return None
    return _finite_float(str(value).replace(",", ""))


# ---------------------------------------------------------------------------
# Layer 1 — fetch seams (sync; never raise)
# ---------------------------------------------------------------------------


def _fetch_risk_table(ak: Any) -> tuple[Any, str, str]:
    """Risk-indicator frame with trade-date walkback.

    Returns (df, requested_date, fail_detail); df None when every calendar
    date in the walkback budget came back empty or raised — weekends and
    holidays simply produce empty SSE frames, so the walkback just tries
    the previous calendar day.
    """
    day = date.today()
    last_error = ""
    day_str = ""
    for _ in range(_TRADE_DATE_WALKBACK_TRIES):
        day_str = day.strftime("%Y%m%d")
        try:
            df = ak.option_risk_indicator_sse(date=day_str)
        except Exception as e:  # noqa: BLE001 - provider seam: any error is a walkback step
            last_error = f"{type(e).__name__}: {e}"
            df = None
        if df is not None and not df.empty:
            return df, day_str, ""
        day -= timedelta(days=1)
    return None, day_str, last_error or "risk indicator empty for every walkback date"


def _join_directory(ak: Any, risk_df: Any) -> tuple[list[dict[str, Any]] | None, int | None]:
    """Inner-join the risk table with the contract directory on contract id.

    Directory dies → (None, None): the caller degrades to PCR-only. The
    underlying code is the 6-digit ETF code inside 标的券名称及代码
    ("50ETF(510050)" → "510050"); 类型 carries SSE's raw label — contains
    购 → call, else put (verified against akshare source: the value passes
    through unmapped).
    """
    try:
        dir_df = ak.option_current_day_sse()
    except Exception as e:  # noqa: BLE001 - provider seam
        logger.warning(f"[sse-options] contract directory failed: {e}")
        return None, None
    if dir_df is None or dir_df.empty:
        return None, None

    dir_by_id: dict[str, Any] = {}
    for _, row in dir_df.iterrows():
        cid = str(row.get("合约交易代码") or "").strip()
        if cid:
            dir_by_id[cid] = row

    contracts: list[dict[str, Any]] = []
    matched: set[str] = set()
    for _, row in risk_df.iterrows():
        cid = str(row.get("CONTRACT_ID") or "").strip()
        drow = dir_by_id.get(cid)
        if drow is None:
            continue
        matched.add(cid)
        underlying = str(drow.get("标的券名称及代码") or "").strip()
        code_match = re.search(r"(\d{6})", underlying)
        contracts.append(
            {
                "contract_id": cid,
                "symbol": code_match.group(1) if code_match else (underlying or None),
                "cp": "C" if "购" in str(drow.get("类型") or "") else "P",
                "strike": _clean_number(drow.get("行权价")),
                "expire_date": str(drow.get("到期日") or "").strip() or None,
                "delta": _finite_float(row.get("DELTA_VALUE")),
                "iv": _finite_float(row.get("IMPLC_VOLATLTY")),
            }
        )
    return contracts, len(dir_by_id) - len(matched)


def _fetch_pcr(ak: Any, trade_date: str) -> dict[str, Any] | None:
    """Official per-underlying volume PCR from the daily stats table."""
    try:
        df = ak.option_daily_stats_sse(date=trade_date)
    except Exception as e:  # noqa: BLE001 - provider seam
        logger.warning(f"[sse-options] daily stats failed for {trade_date}: {e}")
        return None
    if df is None or df.empty:
        return None

    out: dict[str, Any] = {}
    for _, row in df.iterrows():
        code = str(row.get("合约标的代码") or "").strip()
        if not code:
            continue
        out[code] = {
            "name": str(row.get("合约标的名称") or "").strip() or None,
            "pcr_volume": _clean_number(row.get("认沽/认购")),
            "call_volume": _clean_number(row.get("认购成交量")),
            "put_volume": _clean_number(row.get("认沽成交量")),
            "trade_date": str(row.get("交易日") or "").strip() or None,
        }
    return out or None


def fetch_sse_option_snapshot() -> dict[str, Any] | None:
    """One SSE options snapshot: joined per-contract IV surface + official PCR.

    Never raises. Trade-date walkback (today, then previous calendar days,
    six tries) handles weekends/holidays. Partial degradation: risk table
    ok but directory dead → ``status: "degraded"`` with ``contracts: None``
    and PCR intact; daily stats dead → ``pcr_by_underlying: None`` with
    contracts intact; risk table dead → None (nothing to annotate).

    Only ``ok`` snapshots are cached (30-min shared TTL); degraded results
    retry on the next call — failures are never remembered.
    """
    cached = _cache_get(_SNAPSHOT_CACHE_KEY)
    if cached is not None:
        return cached
    try:
        import akshare as ak  # lazy: tests inject a fake via sys.modules
    except ImportError:
        return None

    risk_df, walkback_date, fail_detail = _fetch_risk_table(ak)
    if risk_df is None:
        record_provider_outcome(
            "sse-options", "fail", f"{fail_detail}; walked back to {walkback_date}"
        )
        return None

    as_of = (
        str(risk_df["TRADE_DATE"].iloc[0]).strip()
        if "TRADE_DATE" in risk_df.columns
        else walkback_date
    )
    contracts, n_unmatched = _join_directory(ak, risk_df)
    pcr = _fetch_pcr(ak, walkback_date)

    snapshot: dict[str, Any] = {
        "status": "ok" if contracts is not None else "degraded",
        "as_of": as_of or None,
        "contracts": contracts,
        "pcr_by_underlying": pcr,
        "n_unmatched": n_unmatched,
    }
    degradations = []
    if contracts is None:
        degradations.append("directory failed")
    if pcr is None:
        degradations.append("stats failed")
    detail = f"trade_date={as_of}" + (f" ({', '.join(degradations)})" if degradations else "")
    record_provider_outcome("sse-options", "ok", detail)
    if snapshot["status"] == "ok":
        _cache_set(_SNAPSHOT_CACHE_KEY, snapshot)
    return snapshot


def fetch_qvix_context(store: Any) -> dict[str, Any] | None:
    """QVIX level + 1-year percentile with local-store fallback.

    The host is a third-party site with no SLA: every successful fetch
    upserts the series into ``store`` (sqlite), and an outage serves the
    last known series from there (provider outcome ``fallback``). None only
    when both the fetch fails and the store is empty. Percentile is the
    inclusive rank of the current close among the trailing 252 closes
    (0..1; needs >= 30 rows, else None). Successful contexts are cached
    (30-min shared TTL); None is never cached.
    """
    cached = _cache_get(_QVIX_CACHE_KEY)
    if cached is not None:
        return cached

    fetch_error = ""
    usable = False
    try:
        import akshare as ak  # lazy: tests inject a fake via sys.modules

        df = ak.index_option_50etf_qvix()
        if df is not None and not df.empty and "date" in df.columns and "close" in df.columns:
            rows = [
                (str(d).strip()[:10], close)
                for d, c in zip(df["date"], df["close"])
                if (close := _finite_float(c)) is not None and str(d).strip()[:10]
            ]
            if rows:
                store.upsert_many(rows)
                record_provider_outcome("qvix", "ok")
                usable = True
            else:
                fetch_error = "qvix frame had no usable rows"
        elif df is not None:
            fetch_error = "empty qvix frame"
    except Exception as e:  # noqa: BLE001 - provider seam
        fetch_error = f"{type(e).__name__}: {e}"

    if not usable:
        last = store.last_row()
        if last is None:
            record_provider_outcome("qvix", "fail", fetch_error or "qvix fetch failed")
            return None
        record_provider_outcome("qvix", "fallback", f"{fetch_error}; serving local store")

    closes = store.trailing_closes(_QVIX_WINDOW_DAYS)
    last = store.last_row()
    if not closes or last is None:
        return None  # store unreadable though the fetch succeeded — fail uncached
    current, as_of = last[1], last[0]

    percentile: float | None = None
    if len(closes) >= _QVIX_MIN_ROWS:
        percentile = sum(1 for c in closes if c <= current) / len(closes)
    context = {
        "current": current,
        "as_of": as_of,
        "percentile_1y": percentile,
        "history_days": store.row_count(),
    }
    _cache_set(_QVIX_CACHE_KEY, context)
    return context


# ---------------------------------------------------------------------------
# Layer 2 — pure IV surface metrics
# ---------------------------------------------------------------------------


def _strike_key(row: dict[str, Any]) -> float:
    strike = _finite_float(row.get("strike"))
    return strike if strike is not None else float("inf")


def _atm_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Row whose |delta| is closest to 0.5 (calls preferred, ties → lower strike)."""
    calls = [r for r in rows if r.get("cp") == "C"]
    pool = calls or [r for r in rows if r.get("cp") == "P"]
    if not pool:
        return None
    return min(
        pool,
        key=lambda r: (abs(abs(_finite_float(r.get("delta")) or 0.0) - 0.5), _strike_key(r)),
    )


def _skew_25d(rows: list[dict[str, Any]]) -> float | None:
    """25-delta skew on one expiry's rows: put-wing mean IV − call-wing mean IV.

    Positive = downside protection trades rich (crash-hedging demand).
    """
    put_ivs = [
        iv
        for r in rows
        if r.get("cp") == "P"
        and (delta := _finite_float(r.get("delta"))) is not None
        and -0.35 <= delta <= -0.15
        and (iv := _finite_float(r.get("iv"))) is not None
    ]
    call_ivs = [
        iv
        for r in rows
        if r.get("cp") == "C"
        and (delta := _finite_float(r.get("delta"))) is not None
        and 0.15 <= delta <= 0.35
        and (iv := _finite_float(r.get("iv"))) is not None
    ]
    if not put_ivs or not call_ivs:
        return None
    return sum(put_ivs) / len(put_ivs) - sum(call_ivs) / len(call_ivs)


def compute_iv_metrics(contracts: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """ATM IV per expiry, term structure, and 25-delta skew — pure compute.

    Degenerate rows drop first: IV missing/NaN/<= 0 and delta missing/NaN/
    |delta| >= 0.98 (the deep-ITM rows SSE reports with delta ±1.0 and
    IV 0.0), plus rows without an expiry. Fewer than 10 usable rows → None
    (a surface from a handful of contracts is fabrication).

    Sign conventions (also see the module docstring):
        term_structure = atm_iv_near − atm_iv_next. NEGATIVE means the
        near expiry prices MORE volatility than the next — an inversion
        that flags immediate fear (event risk, crash demand for short-dated
        options). Positive is the normal upward-sloping carry.
        skew_25d = put wing − call wing on the NEAR expiry (doc above).

    ``n_contracts`` counts the input rows; ``n_filtered`` the rows that
    survived the degenerate filter.
    """
    rows: list[dict[str, Any]] = []
    for contract in contracts or []:
        iv = _finite_float(contract.get("iv"))
        delta = _finite_float(contract.get("delta"))
        usable = iv is not None and iv > 0 and delta is not None and abs(delta) < 0.98
        if usable and contract.get("expire_date"):
            rows.append(contract)
    if len(rows) < 10:
        return None

    by_expiry: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_expiry.setdefault(row["expire_date"], []).append(row)
    expiries = sorted(by_expiry)  # ISO-like date strings order correctly

    near_rows = by_expiry[expiries[0]]
    near_atm = _atm_row(near_rows)
    if near_atm is None:
        return None
    metrics: dict[str, Any] = {
        "status": "ok" if _finite_float(near_atm.get("iv")) is not None else "insufficient_data",
        "atm_iv_near": _finite_float(near_atm.get("iv")),
        "near_expiry": expiries[0],
        "atm_iv_next": None,
        "next_expiry": None,
        "term_structure": None,
        "skew_25d": _skew_25d(near_rows),
        "n_contracts": len(contracts or []),
        "n_filtered": len(rows),
    }
    if len(expiries) >= 2:
        next_atm = _atm_row(by_expiry[expiries[1]])
        if next_atm is not None and metrics["atm_iv_near"] is not None:
            metrics["atm_iv_next"] = _finite_float(next_atm.get("iv"))
            metrics["next_expiry"] = expiries[1]
            if metrics["atm_iv_next"] is not None:
                metrics["term_structure"] = metrics["atm_iv_near"] - metrics["atm_iv_next"]
    return metrics


# ---------------------------------------------------------------------------
# Layer 3 — pure PCR aggregation
# ---------------------------------------------------------------------------


def compute_pcr(pcr_by_underlying: dict[str, Any] | None) -> dict[str, Any] | None:
    """Per-underlying passthrough + volume-weighted market PCR.

    ``market_pcr`` sums the underlyings' official volumes (put total /
    call total); underlyings without both volumes > 0 are excluded, and
    fewer than one usable underlying leaves it None.
    """
    if not pcr_by_underlying:
        return None
    call_total = 0.0
    put_total = 0.0
    n_valid = 0
    for entry in pcr_by_underlying.values():
        call_vol = _finite_float((entry or {}).get("call_volume"))
        put_vol = _finite_float((entry or {}).get("put_volume"))
        if call_vol is not None and call_vol > 0 and put_vol is not None and put_vol > 0:
            call_total += call_vol
            put_total += put_vol
            n_valid += 1
    return {
        "by_underlying": dict(pcr_by_underlying),
        "market_pcr": (put_total / call_total) if n_valid >= 1 and call_total > 0 else None,
    }


# ---------------------------------------------------------------------------
# Layer 4 — pure regime label
# ---------------------------------------------------------------------------


def build_option_implied(
    iv_metrics: dict[str, Any] | None,
    pcr: dict[str, Any] | None,
    qvix: dict[str, Any] | None,
) -> dict[str, Any]:
    """Market-level regime label from the QVIX 1-year percentile — 纯标注.

    The percentile is the ONLY regime input by design: QVIX point levels
    are not comparable across volatility regimes, the rank is. Thresholds:
    >= 0.80 恐慌, <= 0.20 自满, otherwise 中性; a missing QVIX or
    percentile gives no regime (``status: insufficient_data`` — honest
    absence, never a fabricated label). This block is annotation-only: no
    score, weight, position size, or decision may read it.
    """
    percentile = qvix.get("percentile_1y") if isinstance(qvix, dict) else None
    regime = None
    if percentile is not None:
        rank = float(percentile)
        regime = "恐慌" if rank >= 0.80 else "自满" if rank <= 0.20 else "中性"
    return {
        "status": "ok" if regime is not None else "insufficient_data",
        "regime": regime,
        "qvix": qvix if isinstance(qvix, dict) else None,
        "iv": iv_metrics if isinstance(iv_metrics, dict) else None,
        "pcr": pcr if isinstance(pcr, dict) else None,
        "generated_at": datetime.now().isoformat(),
    }
