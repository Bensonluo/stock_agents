"""Decision-layer IC evaluation over stored analysis history.

Closes the loop between "what the agent recommended" and "what actually
happened": completed runs are replayed from SQLite, their per-symbol
composite scores are rank-correlated (Spearman IC) against realized
forward returns over a fixed bar horizon, and the per-run ICs aggregate
into ICIR with a t-statistic.

Price history is fetched once per unique symbol (the shared fetcher
cache applies on top) and injected fetchers keep the service testable
offline.
"""

from __future__ import annotations

import json
from bisect import bisect_left
from collections.abc import Awaitable, Callable
from typing import Any

from app.analysis.ic import (
    MIN_IC_SYMBOLS,
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

HistoryFetcher = Callable[[str], Awaitable[dict[str, Any] | None]]


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

    if records is None:
        records = get_database().list_records(status="completed", limit=limit)
    if fetch_history is None:

        async def _default_fetch(symbol: str) -> dict[str, Any] | None:
            return await fetch_historical(symbol, IC_HISTORY_PERIOD)

        fetch_history = _default_fetch

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

    evaluated: list[dict[str, Any]] = []
    pending = 0
    skipped = 0
    dimension_ics: dict[str, list[float]] = {}

    for record in records:
        try:
            result = json.loads(record.result) if record.result else None
        except (json.JSONDecodeError, TypeError):
            result = None
        if not isinstance(result, dict):
            skipped += 1
            continue

        scores = decision_scores(result)
        run_date = (record.created_at or "")[:10]
        if len(scores) < MIN_IC_SYMBOLS or not run_date:
            skipped += 1
            continue

        forward: dict[str, float] = {}
        run_pending = False
        for symbol in scores:
            series = await _series(symbol)
            if series is None:
                continue  # no data at all — the symbol drops out of the cross-section
            dates, closes = series
            entry_i = bisect_left(dates, run_date)
            if entry_i >= len(dates):
                run_pending = True  # run is newer than the series' last bar
                continue
            exit_i = entry_i + horizon_bars
            if exit_i >= len(dates):
                run_pending = True  # forward window not mature yet
                continue
            entry, exit_price = closes[entry_i], closes[exit_i]
            if entry > 0 and exit_price > 0:
                forward[symbol] = exit_price / entry - 1

        ic = information_coefficient(scores, forward)
        if ic is None:
            if run_pending and len(forward) < MIN_IC_SYMBOLS:
                pending += 1
            else:
                skipped += 1
            continue

        evaluated.append(
            {
                "thread_id": record.thread_id,
                "date": run_date,
                "symbols": len(forward),
                "ic": ic,
            }
        )

        # Dimension attribution over the same forward returns — which of
        # technical / fundamental / sentiment actually carries the ranking.
        dimensions = decision_dimension_scores(result)
        for dimension, dim_scores in dimensions.items():
            dim_ic = information_coefficient(dim_scores, forward)
            if dim_ic is not None:
                dimension_ics.setdefault(dimension, []).append(dim_ic)

    summary = ic_summary([run["ic"] for run in evaluated])
    payload: dict[str, Any] = {
        "method": "spearman_rank_ic",
        "horizon_bars": horizon_bars,
        "records_examined": len(records),
        "runs_evaluated": len(evaluated),
        "runs_pending_maturity": pending,
        "runs_skipped": skipped,
        "per_run": evaluated[-20:],
        "dimensions": {
            dimension: ic_summary(ics) if ics else None
            for dimension, ics in sorted(dimension_ics.items())
        },
        "caveat": "Historical runs were produced by evolving decision formulas; "
        "IC aggregates across vintages.",
    }
    if summary is not None:
        payload.update(summary)
        payload["status"] = "ok"
    else:
        payload["status"] = "insufficient_history"
    return payload
