"""Historical calibration of signals (V2 plan §7.2, §8.2).

"How often has this signal actually been right?" — empirical hit rates of a
strategy's entry signals over forward horizons, with sample sizes, Wilson
lower bounds and per-year breakdowns (failure years stay visible). Reported
confidence must be grounded in this table, not in model self-assessment.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.backtest.engine import (
    STRATEGY_PARAMETERS,
    _target_position,  # noqa: PLC2701 - same package family
)

DEFAULT_HORIZONS = (20, 60)
Z_95 = 1.96


def calibrate_signals(
    data: pd.DataFrame,
    *,
    strategy: str,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    benchmark_data: pd.DataFrame | None = None,
    **params: Any,
) -> dict[str, Any]:
    """Empirical hit rates for the strategy's entry signals.

    An entry event is a 0 -> 1 transition of the target position (the same
    deterministic series the engine trades on). For each entry at bar ``i``
    the forward return over ``horizon`` bars is measured close-to-close;
    a hit means the return beat the benchmark over the same window (or was
    simply positive when no benchmark is supplied).
    """
    if strategy not in STRATEGY_PARAMETERS:
        raise ValueError(f"Unknown strategy: {strategy}")
    unknown = set(params) - STRATEGY_PARAMETERS[strategy]
    if unknown:
        raise ValueError(f"Unknown parameter for {strategy}: {sorted(unknown)[0]}")
    if any(h <= 0 for h in horizons):
        raise ValueError("horizons must be positive")

    close = data["Close"]
    target = _target_position(data, strategy, {**_defaulted(strategy), **params})
    entries = _entry_indices(target)

    benchmark_close = None
    if benchmark_data is not None and not benchmark_data.empty:
        aligned = benchmark_data["Close"].reindex(data.index).ffill()
        benchmark_close = aligned

    by_horizon: dict[str, Any] = {}
    for horizon in horizons:
        results = [
            _outcome(int(i), int(horizon), close, benchmark_close, str(data.index[i]))
            for i in entries
            if i + horizon < len(data)
        ]
        by_horizon[str(horizon)] = _summarize(results, horizon)

    return {
        "strategy": strategy,
        "params": {**_defaulted(strategy), **params},
        "entries_total": len(entries),
        "by_horizon": by_horizon,
    }


def wilson_lower_bound(wins: int, n: int, z: float = Z_95) -> float | None:
    """Lower bound of the Wilson score interval — conservative hit-rate floor."""
    if n <= 0:
        return None
    phat = wins / n
    denom = 1 + z * z / n
    centre = phat + z * z / (2 * n)
    margin = z * ((phat * (1 - phat) + z * z / (4 * n)) / n) ** 0.5
    return round((centre - margin) / denom, 6)


def _entry_indices(target: pd.Series) -> list[int]:
    """Indices where the position transitions 0 -> 1."""
    previous = target.shift(1).fillna(0.0)
    return [int(i) for i in range(len(target)) if target.iloc[i] > 0 and previous.iloc[i] <= 0]


def _outcome(
    i: int, horizon: int, close: pd.Series, benchmark_close: pd.Series | None, date: Any
) -> dict[str, Any] | None:
    entry_price = float(close.iloc[i])
    exit_price = float(close.iloc[i + horizon])
    if not (entry_price > 0 and exit_price > 0):
        return None
    forward_return = exit_price / entry_price - 1

    if benchmark_close is not None:
        bench_entry = float(benchmark_close.iloc[i])
        bench_exit = float(benchmark_close.iloc[i + horizon])
        if not (bench_entry > 0 and bench_exit > 0):
            return None
        hit = forward_return > (bench_exit / bench_entry - 1)
    else:
        hit = forward_return > 0

    return {"date": str(date), "forward_return": forward_return, "hit": bool(hit)}


def _summarize(results: list[dict[str, Any]], horizon: int) -> dict[str, Any]:
    """Aggregate outcomes: hit rate, Wilson floor, per-year detail."""
    if not results:
        return {"events": 0, "hit_rate": None, "wilson_lower": None, "by_year": {}}

    wins = sum(1 for r in results if r["hit"])
    by_year: dict[str, dict[str, Any]] = {}
    for r in results:
        year = str(r["date"])[:4]
        bucket = by_year.setdefault(year, {"events": 0, "hits": 0})
        bucket["events"] += 1
        bucket["hits"] += int(r["hit"])

    return {
        "events": len(results),
        "hit_rate": round(wins / len(results), 6),
        "wilson_lower": wilson_lower_bound(wins, len(results)),
        "avg_forward_return": round(sum(r["forward_return"] for r in results) / len(results), 6),
        "by_year": {
            year: {
                "events": bucket["events"],
                "hit_rate": round(bucket["hits"] / bucket["events"], 6),
            }
            for year, bucket in sorted(by_year.items())
        },
    }


def _defaulted(strategy: str) -> dict[str, Any]:
    from app.backtest.engine import DEFAULT_PARAMS

    return dict(DEFAULT_PARAMS[strategy])
