"""Random-entry Monte Carlo null benchmark ("signal or noise").

The null permutes the strategy's actual holding segments onto random start
bars and re-runs the same simulator, so a strategy only scores well when its
TIMING — not its trade count, holding lengths, costs, or market exposure —
beats chance on the same tape.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.backtest import CN_STOCK, US_STOCK, ZERO, run_backtest
from app.backtest.null_benchmark import (
    NULL_MAX_EXPOSURE,
    _place_segments,
    holding_segments,
    random_entry_null,
)


def _tape(closes: list[float]) -> pd.DataFrame:
    """Gap-free OHLC frame: open of bar t is close of t-1."""
    opens = [closes[0]] + closes[:-1]
    index = pd.bdate_range("2024-01-01", periods=len(closes))
    return pd.DataFrame(
        {
            "Open": opens,
            "High": [max(o, c) * 1.005 for o, c in zip(opens, closes)],
            "Low": [min(o, c) * 0.995 for o, c in zip(opens, closes)],
            "Close": closes,
            "Volume": [1_000_000.0] * len(closes),
        },
        index=index,
    )


def _sawtooth(n_blocks: int = 10, leg: int = 10) -> list[float]:
    """Deterministic up-10%/down-5% blocks — timing is the only edge."""
    closes = [100.0]
    for block in range(n_blocks):
        move = 0.01 if block % 2 == 0 else -0.005
        for _ in range(leg):
            closes.append(closes[-1] * (1 + move))
    return closes


class TestRandomEntryNull:
    def test_perfect_timing_crushes_the_null(self) -> None:
        closes = _sawtooth()
        data = _tape(closes)
        # Hold exactly through the up-legs (perfect foresight target): its
        # return must sit far in the null's upper tail.
        target = pd.Series(0.0, index=data.index)
        for block in range(0, 10, 2):  # even blocks are the +1% legs
            target.iloc[block * 10 : (block + 1) * 10] = 1.0

        block = random_entry_null(
            data, target, 0.8, ZERO, initial_cash=10_000.0, iterations=200, seed=42
        )
        assert block is not None
        assert block["segments"] == 5
        assert block["matched_round_trips"] == 5
        assert block["percentile"] >= 0.95
        assert block["p_value"] <= 0.05
        # Percentile and p_value partition the draws (ties counted as wins).
        assert block["percentile"] + block["p_value"] == 1.0

    def test_no_round_trips_returns_none(self) -> None:
        data = _tape(_sawtooth(n_blocks=6))
        target = pd.Series(0.0, index=data.index)
        assert random_entry_null(data, target, 0.0, ZERO, 10_000.0) is None

    def test_full_exposure_has_no_placement_freedom(self) -> None:
        # buy-and-hold: one segment spanning every bar — permuting it has
        # nowhere to go, so the honest answer is no benchmark, not a
        # degenerate one that always ties.
        data = _tape(_sawtooth(n_blocks=6))
        target = pd.Series(1.0, index=data.index)
        assert random_entry_null(data, target, 0.1, ZERO, 10_000.0) is None

    def test_exposure_guard_boundary(self) -> None:
        data = _tape(_sawtooth(n_blocks=10))
        target = pd.Series(0.0, index=data.index)
        holding = int(NULL_MAX_EXPOSURE * len(data)) + 1  # just over the cap
        target.iloc[:holding] = 1.0
        assert random_entry_null(data, target, 0.0, ZERO, 10_000.0, iterations=10) is None

    def test_deterministic_given_seed(self) -> None:
        data = _tape(_sawtooth())
        target = pd.Series(0.0, index=data.index)
        target.iloc[10:30] = 1.0
        target.iloc[50:80] = 1.0
        target.iloc[90:95] = 1.0

        first = random_entry_null(data, target, 0.05, US_STOCK, 10_000.0, iterations=50)
        second = random_entry_null(data, target, 0.05, US_STOCK, 10_000.0, iterations=50)
        other_seed = random_entry_null(
            data, target, 0.05, US_STOCK, 10_000.0, iterations=50, seed=7
        )
        assert first == second
        assert other_seed is not None and first is not None
        assert other_seed["null_return_mean"] != first["null_return_mean"]

    def test_null_pays_the_same_cost_model(self) -> None:
        # Same tape, same placements (same seed): the CN preset (stamp tax,
        # min commission, slippage) must drag the null mean below ZERO costs.
        data = _tape(_sawtooth())
        target = pd.Series(0.0, index=data.index)
        target.iloc[10:30] = 1.0
        target.iloc[50:80] = 1.0
        target.iloc[90:95] = 1.0

        free = random_entry_null(data, target, 0.05, ZERO, 10_000.0, iterations=100)
        taxed = random_entry_null(data, target, 0.05, CN_STOCK, 10_000.0, iterations=100)
        assert free is not None and taxed is not None
        assert taxed["null_return_mean"] < free["null_return_mean"]

    def test_placements_never_overlap_and_preserve_lengths(self) -> None:
        rng = np.random.default_rng(3)
        placed = _place_segments(100, [20, 15, 10, 10, 5], rng)
        assert sorted(length for _, length in placed) == [5, 10, 10, 15, 20]
        occupied = np.zeros(100, dtype=bool)
        for start, length in placed:
            assert not occupied[start : start + length].any()
            occupied[start : start + length] = True

    def test_holding_segments_counts_runs(self) -> None:
        target = pd.Series([0.0, 1, 1, 0, 1, 0, 0, 1, 1, 1])
        assert holding_segments(target) == [2, 1, 3]


class TestPlacementGaps:
    """Adjacent placements merge into ONE position in the simulator's mask,
    so the draw pays fewer fees than the strategy while the report claims a
    full match — the null must keep segments apart and validate the count."""

    def test_placements_keep_one_empty_bar_between(self) -> None:
        # 40 one-day segments on 100 bars: feasible with gaps (80 <= 100).
        rng = np.random.default_rng(42)
        placed = _place_segments(100, [1] * 40, rng)
        assert len(placed) == 40
        ordered = sorted(placed)
        for (start, length), (next_start, _) in zip(ordered, ordered[1:]):
            assert next_start >= start + length + 1  # at least one empty bar

    def test_draws_pay_exactly_the_reported_round_trips(self) -> None:
        # The review repro: dense one-day segments used to merge into fewer
        # actual positions — draws paid fewer fees than the report claimed.
        # On a flat tape every round trip costs the same regardless of
        # position, so once placements stop merging, all draws pay between
        # segments-1 and segments fee pairs and the return spread collapses
        # to at most one round trip's costs (the final-bar segment gets no
        # fill bar — the strategy would not have either).
        data = _tape([100.0] * 300)
        target = pd.Series(0.0, index=data.index)
        target.iloc[0:40:2] = 1.0  # 20 one-day segments, sparse → no drops
        block = random_entry_null(data, target, -0.113, US_STOCK, 10_000.0, iterations=60, seed=42)
        assert block is not None
        assert block["segments"] == 20
        # Honest reporting: the minimum ACTUAL round trips across retained
        # draws, never the placement count while an actual count ran lower.
        assert block["matched_round_trips"] >= block["segments"] - 1
        # Pre-fix, merged placements spread returns across the whole fee
        # range (27..40 round trips on the review's numbers).
        assert block["null_return_p95"] - block["null_return_p05"] < 0.01


class TestEngineIntegration:
    def test_default_run_has_no_null(self) -> None:
        result = run_backtest(_tape(_sawtooth()), strategy="sma_crossover")
        assert result.null_benchmark is None
        assert "null_benchmark" not in result.metrics

    def test_opt_in_run_carries_the_null(self) -> None:
        result = run_backtest(
            _tape(_sawtooth()),
            strategy="sma_crossover",
            cost_model=US_STOCK,
            null_iterations=60,
        )
        block = result.null_benchmark
        assert block is not None
        assert block["iterations"] == 60
        assert block["strategy_return"] == result.metrics["total_return"]
        assert block["percentile"] + block["p_value"] == 1.0
        # The engine surfaces the same block inside the metric suite.
        assert result.metrics["null_benchmark"] is block

    def test_buy_and_hold_opt_in_still_gets_none(self) -> None:
        result = run_backtest(_tape(_sawtooth()), strategy="buy_and_hold", null_iterations=20)
        assert result.null_benchmark is None
        assert "null_benchmark" not in result.metrics
