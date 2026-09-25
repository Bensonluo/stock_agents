"""Decision-layer IC evaluation over stored analysis history.

Closes the loop between "what the agent recommended" and "what actually
happened": completed runs are replayed from SQLite, their per-symbol
composite scores are rank-correlated (Spearman IC) against realized
forward returns over a fixed bar horizon, and the per-run ICs aggregate
into ICIR with a t-statistic.

The replay core is horizon-generic: one pass over the records computes
entry bars once and evaluates every requested horizon against the same
fetched series, so the decay curve (IC as the forward window lengthens)
costs no extra network work. Price history is fetched once per unique
symbol per call, and the production path sits on a 30-min service cache
(``_cached_default_fetch``) — daily data needs no per-view freshness.
Injected fetchers bypass that cache and keep the service testable offline.
"""

from __future__ import annotations

import json
from bisect import bisect_left
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any

from app.analysis.forecast_calibration import (
    brier_score,
    brier_skill_score,
    claim_correct,
    directional_claims,
    reliability_curve,
)
from app.analysis.ic import (
    MIN_IC_SYMBOLS,
    STATIC_DIMENSION_WEIGHTS,
    adaptive_dimension_weights,
    decision_dimension_scores,
    decision_scores,
    ic_summary,
    information_coefficient,
)
from app.storage.database import AnalysisRecord, get_database
from app.tools.data.fetcher import fetch_historical
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Runs older than the fetched window simply have no entry bar — they fall
# out of the cross-section rather than corrupting it. 5y comfortably covers
# a research history that itself began in 2026.
IC_HISTORY_PERIOD = "5y"

# Decay-curve defaults (trading bars): one week to one quarter of holding.
DEFAULT_DECAY_HORIZONS = (5, 10, 20, 60)
MAX_DECAY_HORIZONS = 6
MAX_HORIZON_BARS = 250

CAVEAT = (
    "Historical runs were produced by evolving decision formulas; " "IC aggregates across vintages."
)

CALIBRATION_CAVEAT = (
    CAVEAT + " Confidence is a heuristic composite, not a fitted probability; "
    "Brier here measures how far it is from behaving like one."
)

# Replay price fetches are evaluation reads of daily data. The shared
# fetcher's 60s TTL is a freshness budget for live analysis; applying it
# here would refetch every symbol's 5y history on each panel view (the
# quality card alone fires three replay endpoints). Cache at the service
# layer instead. Failures are never cached — a transient fetch outage
# must not poison 30 minutes of replays.
REPLAY_SERIES_TTL = 1800.0
_replay_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}

HistoryFetcher = Callable[[str], Awaitable[dict[str, Any] | None]]

# Per-horizon replay accumulators.
_Bucket = dict[str, Any]


def _new_bucket() -> _Bucket:
    return {"evaluated": [], "pending": 0, "skipped": 0, "dimension_ics": {}}


async def _cached_default_fetch(symbol: str) -> dict[str, Any] | None:
    """Production fetch path: 30-min service cache over the shared fetcher.

    Injected fetchers (tests) never pass through here — a global cache over
    test doubles would leak results across tests. Only successful fetches
    are cached; ``None`` retries on the next call.
    """
    now = monotonic()
    hit = _replay_cache.get(symbol)
    if hit is not None and now - hit[0] < REPLAY_SERIES_TTL:
        return hit[1]
    data = await fetch_historical(symbol, IC_HISTORY_PERIOD)
    if data is not None:
        _replay_cache[symbol] = (now, data)
    return data


def _resolve_inputs(
    records: list[AnalysisRecord] | None,
    limit: int,
    fetch_history: HistoryFetcher | None,
) -> tuple[list[AnalysisRecord], HistoryFetcher]:
    if records is None:
        records = get_database().list_records(status="completed", limit=limit)
        fetch_history = _cached_default_fetch
    elif fetch_history is None:
        # Pre-fetched records but no fetcher (offline tests): keep the
        # pass-through default rather than the caching path.
        async def _default_fetch(symbol: str) -> dict[str, Any] | None:
            return await fetch_historical(symbol, IC_HISTORY_PERIOD)

        fetch_history = _default_fetch
    return records, fetch_history


async def _replay(
    horizons: list[int],
    records: list[AnalysisRecord],
    fetch_history: HistoryFetcher,
) -> dict[int, _Bucket]:
    """One pass over records; every horizon evaluated against the same series.

    A run newer than a series' last bar, or whose forward window has not
    matured at a given horizon, counts as pending at that horizon — maturity
    is a per-horizon judgement, not a run-level one.
    """
    buckets: dict[int, _Bucket] = {h: _new_bucket() for h in horizons}
    series_cache: dict[str, tuple[list[str], list[float]] | None] = {}

    async def _series(symbol: str) -> tuple[list[str], list[float]] | None:
        if symbol not in series_cache:
            try:
                data = await fetch_history(symbol)
            except Exception as e:  # noqa: BLE001 - one dead symbol must not sink the run
                logger.warning(f"[ic] history fetch failed for {symbol}: {e}")
                data = None
            series_cache[symbol] = (
                (list(data["dates"]), [float(c) for c in data["close"]])
                if data and data.get("dates") and data.get("close")
                else None
            )
        return series_cache[symbol]

    for record in records:
        try:
            result = json.loads(record.result) if record.result else None
        except (json.JSONDecodeError, TypeError):
            result = None
        if not isinstance(result, dict):
            for bucket in buckets.values():
                bucket["skipped"] += 1
            continue

        scores = decision_scores(result)
        dimensions = decision_dimension_scores(result)
        run_date = (record.created_at or "")[:10]
        if len(scores) < MIN_IC_SYMBOLS or not run_date:
            for bucket in buckets.values():
                bucket["skipped"] += 1
            continue

        # Entry bar per symbol is horizon-independent — compute once.
        no_entry_bar = False
        entries: dict[str, tuple[int, list[float]]] = {}
        for symbol in scores:
            series = await _series(symbol)
            if series is None:
                continue  # no data at all — the symbol drops out of the cross-section
            dates, closes = series
            entry_i = bisect_left(dates, run_date)
            if entry_i >= len(dates):
                no_entry_bar = True  # run is newer than the series' last bar
                continue
            entries[symbol] = (entry_i, closes)

        for horizon, bucket in buckets.items():
            forward: dict[str, float] = {}
            run_pending = no_entry_bar
            for symbol, (entry_i, closes) in entries.items():
                exit_i = entry_i + horizon
                if exit_i >= len(closes):
                    run_pending = True  # forward window not mature yet
                    continue
                entry, exit_price = closes[entry_i], closes[exit_i]
                if entry > 0 and exit_price > 0:
                    forward[symbol] = exit_price / entry - 1

            ic = information_coefficient(scores, forward)
            if ic is None:
                if run_pending and len(forward) < MIN_IC_SYMBOLS:
                    bucket["pending"] += 1
                else:
                    bucket["skipped"] += 1
                continue

            bucket["evaluated"].append(
                {
                    "thread_id": record.thread_id,
                    "date": run_date,
                    "symbols": len(forward),
                    "ic": ic,
                }
            )

            # Dimension attribution over the same forward returns — which of
            # technical / fundamental / sentiment actually carries the ranking.
            for dimension, dim_scores in dimensions.items():
                dim_ic = information_coefficient(dim_scores, forward)
                if dim_ic is not None:
                    bucket["dimension_ics"].setdefault(dimension, []).append(dim_ic)

    return buckets


def _bucket_payload(
    bucket: _Bucket,
    horizon_bars: int,
    records_examined: int,
    *,
    with_dimensions: bool,
) -> dict[str, Any]:
    summary = ic_summary([run["ic"] for run in bucket["evaluated"]])
    payload: dict[str, Any] = {
        "method": "spearman_rank_ic",
        "horizon_bars": horizon_bars,
        "records_examined": records_examined,
        "runs_evaluated": len(bucket["evaluated"]),
        "runs_pending_maturity": bucket["pending"],
        "runs_skipped": bucket["skipped"],
        "per_run": bucket["evaluated"][-20:],
    }
    if with_dimensions:
        payload["dimensions"] = {
            dimension: ic_summary(ics) if ics else None
            for dimension, ics in sorted(bucket["dimension_ics"].items())
        }
    payload["caveat"] = CAVEAT
    if summary is not None:
        payload.update(summary)
        payload["status"] = "ok"
    else:
        payload["status"] = "insufficient_history"
    return payload


async def evaluate_decision_ic(
    *,
    horizon_bars: int = 20,
    limit: int = 200,
    records: list[AnalysisRecord] | None = None,
    fetch_history: HistoryFetcher | None = None,
) -> dict[str, Any]:
    """Rank IC / ICIR of decision-layer scores against realized returns.

    Args:
        horizon_bars: forward window in trading bars (matches the calibration
            module's convention).
        limit: how many completed records to examine, newest first.
        records: pre-fetched records (tests); defaults to the history DB.
        fetch_history: injectable ``{symbol -> dates/close}`` provider.

    Returns:
        Aggregated IC block; ``status="insufficient_history"`` when too few
        runs are mature enough to evaluate — never a fabricated number.
    """
    if horizon_bars <= 0:
        raise ValueError("horizon_bars must be positive")

    records, fetch_history = _resolve_inputs(records, limit, fetch_history)
    bucket = (await _replay([horizon_bars], records, fetch_history))[horizon_bars]
    return _bucket_payload(bucket, horizon_bars, len(records), with_dimensions=True)


def _normalize_horizons(horizons: list[int] | tuple[int, ...]) -> list[int]:
    unique = sorted({int(h) for h in horizons})
    if not unique or any(h < 1 or h > MAX_HORIZON_BARS for h in unique):
        raise ValueError(f"horizons must be 1-{MAX_HORIZON_BARS} trading bars")
    if len(unique) > MAX_DECAY_HORIZONS:
        raise ValueError(f"at most {MAX_DECAY_HORIZONS} horizons supported")
    return unique


async def evaluate_ic_decay(
    *,
    horizons: list[int] | tuple[int, ...] = DEFAULT_DECAY_HORIZONS,
    limit: int = 200,
    records: list[AnalysisRecord] | None = None,
    fetch_history: HistoryFetcher | None = None,
) -> dict[str, Any]:
    """IC at multiple forward windows — the signal's decay curve.

    One replay pass evaluates every horizon against the same per-symbol
    series (one network fetch per unique symbol, regardless of horizon
    count). Each horizon is judged independently for maturity: a run mature
    at 5 bars may still be pending at 60. The curve answers "how long does
    the ranking actually persist" — the signal's natural holding period.
    """
    horizons = _normalize_horizons(horizons)
    records, fetch_history = _resolve_inputs(records, limit, fetch_history)
    buckets = await _replay(horizons, records, fetch_history)

    points = [_bucket_payload(buckets[h], h, len(records), with_dimensions=False) for h in horizons]
    return {
        "method": "spearman_rank_ic_decay",
        "horizons": points,
        "status": "ok" if any(p["status"] == "ok" for p in points) else ("insufficient_history"),
        "caveat": CAVEAT,
    }


async def evaluate_confidence_calibration(
    *,
    horizon_bars: int = 20,
    limit: int = 200,
    records: list[AnalysisRecord] | None = None,
    fetch_history: HistoryFetcher | None = None,
) -> dict[str, Any]:
    """Calibrate decision-layer confidence against realized outcomes.

    A sibling of the IC replay with different unit of analysis: the IC
    needs a cross-section (>= MIN_IC_SYMBOLS symbols to rank), while a
    single directional claim is calibratable on its own — one symbol's
    "buy at 0.8" is one probabilistic prediction, mature or not. Each
    run's buy/sell claims are scored over the same forward window; holds
    assert no direction and contribute nothing.

    Returns:
        Brier / Brier-skill / reliability block; ``status="insufficient_history"``
        when no mature directional claim exists — never a fabricated number.
    """
    if horizon_bars <= 0:
        raise ValueError("horizon_bars must be positive")

    records, fetch_history = _resolve_inputs(records, limit, fetch_history)

    pairs: list[tuple[float, bool]] = []
    runs_evaluated = 0
    runs_pending = 0
    runs_skipped = 0
    series_cache: dict[str, tuple[list[str], list[float]] | None] = {}

    async def _series(symbol: str) -> tuple[list[str], list[float]] | None:
        if symbol not in series_cache:
            try:
                data = await fetch_history(symbol)
            except Exception as e:  # noqa: BLE001 - one dead symbol must not sink the run
                logger.warning(f"[calibration] history fetch failed for {symbol}: {e}")
                data = None
            series_cache[symbol] = (
                (list(data["dates"]), [float(c) for c in data["close"]])
                if data and data.get("dates") and data.get("close")
                else None
            )
        return series_cache[symbol]

    for record in records:
        try:
            result = json.loads(record.result) if record.result else None
        except (json.JSONDecodeError, TypeError):
            result = None
        if not isinstance(result, dict):
            runs_skipped += 1
            continue

        claims = directional_claims(result)
        run_date = (record.created_at or "")[:10]
        if not claims or not run_date:
            runs_skipped += 1
            continue

        run_pairs: list[tuple[float, bool]] = []
        pending = False
        for symbol, (direction, confidence) in claims.items():
            series = await _series(symbol)
            if series is None:
                continue  # no data at all — the claim drops out
            dates, closes = series
            entry_i = bisect_left(dates, run_date)
            if entry_i >= len(dates):
                pending = True
                continue
            exit_i = entry_i + horizon_bars
            if exit_i >= len(closes):
                pending = True
                continue
            entry, exit_price = closes[entry_i], closes[exit_i]
            if entry > 0 and exit_price > 0:
                run_pairs.append((confidence, claim_correct(direction, exit_price / entry - 1)))

        pairs.extend(run_pairs)
        if run_pairs:
            runs_evaluated += 1
        elif pending:
            runs_pending += 1
        else:
            runs_skipped += 1

    payload: dict[str, Any] = {
        "method": "brier_reliability",
        "horizon_bars": horizon_bars,
        "records_examined": len(records),
        "runs_evaluated": runs_evaluated,
        "runs_pending_maturity": runs_pending,
        "runs_skipped": runs_skipped,
        "caveat": CALIBRATION_CAVEAT,
    }
    if not pairs:
        payload.update(predictions=0, status="insufficient_history")
        return payload

    outcomes = [1.0 if hit else 0.0 for _, hit in pairs]
    payload.update(
        predictions=len(pairs),
        base_rate=round(sum(outcomes) / len(outcomes), 4),
        avg_confidence=round(sum(p for p, _ in pairs) / len(pairs), 4),
        brier_score=brier_score(pairs),
        brier_skill_score=brier_skill_score(pairs),
        reliability=reliability_curve(pairs),
        status="ok",
    )
    return payload


# ---------------------------------------------------------------------------
# IC-driven dimension weights: the feedback edge of the IC loop. The IC
# evidence computed above feeds back into the recommendation blend via
# adaptive_dimension_weights; this provider is the async, cached boundary
# the decision layer calls.
# ---------------------------------------------------------------------------

# Weights evidence updates at most every 30 minutes — the same freshness
# budget as the replay series cache, and cheap enough that every run of the
# decision pipeline can afford one consult.
WEIGHTS_EVIDENCE_TTL = 1800.0
_weights_cache: tuple[float, tuple[dict[str, float], dict[str, Any]]] | None = None


async def get_adaptive_dimension_weights(
    *,
    horizon_bars: int = 20,
    records: list[AnalysisRecord] | None = None,
    fetch_history: HistoryFetcher | None = None,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Dimension weights blended toward measured IC, with provenance.

    The decision layer's consult point: static weights unless every
    directional dimension has a qualified IC summary (runs and dispersion
    gates live in ``adaptive_dimension_weights``). Never raises — a weights
    experiment must not take the decision pipeline down; any failure
    returns the static blend with the reason recorded.

    Cached 30 min on the production path only (no injected records/
    fetcher); injected calls recompute so tests stay isolated.
    """
    global _weights_cache
    from app.config import settings

    static = dict(STATIC_DIMENSION_WEIGHTS)
    default_path = records is None and fetch_history is None
    if default_path and not settings.ic_adaptive_weights_enabled:
        return static, {
            "mode": "static",
            "reason": "disabled (ic_adaptive_weights_enabled=false)",
            "static_weights": static,
            "weights": static,
            "lambda": None,
            "runs_weakest_dimension": None,
            "targets": None,
            "per_dimension": {},
        }

    now = monotonic()
    if (
        default_path
        and _weights_cache is not None
        and now - _weights_cache[0] < WEIGHTS_EVIDENCE_TTL
    ):
        return _weights_cache[1]

    try:
        payload = await evaluate_decision_ic(
            horizon_bars=horizon_bars, records=records, fetch_history=fetch_history
        )
        weights, provenance = adaptive_dimension_weights(payload.get("dimensions") or {})
        provenance["horizon_bars"] = horizon_bars
        provenance["runs_evaluated"] = payload.get("runs_evaluated")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Adaptive weights fell back to static: {exc}")
        return static, {
            "mode": "static",
            "reason": f"evidence unavailable ({type(exc).__name__})",
            "static_weights": static,
            "weights": static,
            "lambda": None,
            "runs_weakest_dimension": None,
            "targets": None,
            "per_dimension": {},
        }

    result = (weights, provenance)
    if default_path:
        _weights_cache = (now, result)
    return result


def peek_dimension_weights() -> tuple[dict[str, float], dict[str, Any]] | None:
    """Synchronous snapshot of the cached weights, or ``None`` when cold.

    For callers that cannot await (the ReAct report path's validator): they
    read the snapshot the async decision path primed; a cold process uses
    the static blend — recorded in that run's own provenance.
    """
    if _weights_cache is None or monotonic() - _weights_cache[0] >= WEIGHTS_EVIDENCE_TTL:
        return None
    return _weights_cache[1]
