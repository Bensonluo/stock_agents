"""Monte Carlo random-entry null benchmark ("signal or noise").

A strategy that returned +12% with 8 round trips over a window has no
answer yet to the only question that matters: would 8 random entries with
the same holding lengths, on the same bars, paying the same costs, have
done just as well? This module builds that null distribution by permuting
the strategy's actual holding segments onto random start bars and re-running
the SAME simulation loop (next-open fills, cost model, force-liquidation) —
so the comparison is exact on mechanics and differs only in timing.

Adapted from the Monte Carlo null-portfolio validation used for multi-agent
recommendation systems (matched universe/dates/holdings/weighting; 10k
random portfolios, empirical p-value), translated from portfolio selection
to signal timing for a single-symbol rule engine.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.backtest.costs import CostModel

# Default draw count. The paper uses 10,000 cheap linear-algebra portfolios;
# each of our draws is a full bar-by-bar simulation, so the default trades
# resolution (±~3% on a p-value) for interactive latency.
NULL_ITERATIONS = 300

# Random placement needs room: if the strategy is in the market for more
# than this fraction of bars, permuting its segments has (almost) nowhere
# to go — buy-and-hold-style runs return no benchmark rather than a
# degenerate one.
NULL_MAX_EXPOSURE = 0.8

# Retries before a segment is dropped from one null draw.
PLACEMENT_ATTEMPTS = 60


def holding_segments(target: pd.Series) -> list[int]:
    """Lengths of the contiguous in-market runs of a target-position series."""
    in_market = (target.to_numpy() > 0).tolist()
    lengths: list[int] = []
    run = 0
    for flag in in_market:
        if flag:
            run += 1
        elif run:
            lengths.append(run)
            run = 0
    if run:
        lengths.append(run)
    return lengths


def _place_segments(
    n_bars: int, lengths: list[int], rng: np.random.Generator
) -> list[tuple[int, int]]:
    """Scatter the holding lengths over random start bars, always separated
    by at least one empty bar.

    The gap is not cosmetic: adjacent segments collapse into ONE position in
    the simulator's 0/1 target mask, so the draw would pay one fee pair where
    the strategy paid several — the exact cost-matching the null exists to
    preserve. Segment order is shuffled per draw so a segment is equally
    likely to land anywhere; a placement that cannot fit after
    PLACEMENT_ATTEMPTS tries is dropped (the draw simply has one fewer round
    trip). Full placement freedom, including holding into the final bar —
    the strategy itself may end in the market and be liquidated.
    """
    # One extra slot so the mandatory empty bar after a segment that reaches
    # the final bar has somewhere to live without an out-of-bounds write.
    occupied = np.zeros(n_bars + 1, dtype=bool)
    placed: list[tuple[int, int]] = []
    for length in rng.permutation(lengths):
        length = int(length)
        for _ in range(PLACEMENT_ATTEMPTS):
            start = int(rng.integers(0, n_bars - length + 1))
            # The gap bar after the segment must be free too, or this
            # placement would butt against the next one downstream.
            if not occupied[start : start + length + 1].any():
                occupied[start : start + length] = True
                occupied[start + length] = True  # mandatory empty bar
                placed.append((start, length))
                break
    return placed


def random_entry_null(
    data: pd.DataFrame,
    target: pd.Series,
    strategy_return: float,
    cost_model: CostModel,
    initial_cash: float,
    *,
    iterations: int = NULL_ITERATIONS,
    seed: int = 42,
) -> dict[str, Any] | None:
    """Empirical null distribution of total return under random entry timing.

    Args:
        data: The exact OHLCV frame the strategy ran on.
        target: The strategy's target-position series (same index).
        strategy_return: The strategy run's total return (the statistic the
            null distribution is compared against).
        cost_model: Same cost model as the strategy run.
        initial_cash: Same starting equity.
        iterations: Number of random-timing draws (>= 2 for a percentile).
        seed: Fixed default keeps the benchmark a deterministic property of
            the data — any seed's sample is as valid as another's.

    Returns:
        Null-distribution summary with the strategy return's percentile and
        one-sided p-value, or ``None`` when no meaningful null exists (no
        round trips, or exposure leaves no placement freedom).

        Every reported draw makes exactly ``segments`` round trips: placements
        keep one empty bar between segments (adjacent segments would merge
        into one fee-paying position in the simulator's mask), and each draw's
        actual round-trip count — read off the simulator's own trades — is
        validated against the placement count, with mismatched draws rejected.
        ``matched_round_trips`` is the minimum actual count across retained
        draws.
    """
    n_bars = len(data)
    lengths = holding_segments(target)
    if not lengths or iterations < 2 or n_bars < 10:
        return None
    if sum(lengths) > NULL_MAX_EXPOSURE * n_bars:
        return None

    rng = np.random.default_rng(seed)
    # Deferred: engine imports this module at load time for the opt-in
    # benchmark, so reaching back for its simulator must happen at call time.
    from app.backtest.engine import _simulate

    null_returns: list[float] = []
    matched = len(lengths)
    for _ in range(iterations):
        placed = _place_segments(n_bars, lengths, rng)
        if not placed:
            continue
        null_target = np.zeros(n_bars)
        for start, length in placed:
            null_target[start : start + length] = 1.0
        equity, trades, _ = _simulate(
            data, pd.Series(null_target, index=data.index), cost_model, initial_cash
        )
        # Honesty gate: a placed segment produces one round trip iff it has
        # a fill bar after it (next-open fills) — a segment starting on the
        # final bar gets none, exactly as it would for the strategy. Count
        # what the simulator actually paid for and reject any draw whose
        # count drifted from that expectation (e.g. a merged or skipped
        # fill); the gap rule makes this a pure invariant, but the gate keeps
        # ``matched_round_trips`` honest even if placement logic ever drifts.
        expected = sum(1 for start, _ in placed if start < n_bars - 1)
        actual = sum(1 for trade in trades if trade.get("action") == "sell")
        if actual != expected:
            continue
        matched = min(matched, actual)
        null_returns.append(float(equity.iloc[-1] / equity.iloc[0] - 1))

    if len(null_returns) < 2:
        return None

    draws = np.asarray(null_returns)
    wins = int(np.sum(draws >= strategy_return))
    return {
        "method": "random_entry_monte_carlo",
        "iterations": len(null_returns),
        "seed": seed,
        "segments": len(lengths),
        "matched_round_trips": matched,
        "strategy_return": round(strategy_return, 6),
        "null_return_mean": round(float(draws.mean()), 6),
        "null_return_std": round(float(draws.std(ddof=1)), 6),
        "null_return_p05": round(float(np.percentile(draws, 5)), 6),
        "null_return_p50": round(float(np.percentile(draws, 50)), 6),
        "null_return_p95": round(float(np.percentile(draws, 95)), 6),
        "percentile": round(float(np.mean(draws < strategy_return)), 4),
        "p_value": round(wins / len(null_returns), 4),
    }
