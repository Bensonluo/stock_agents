"""Top-k portfolio replay — the money-terms sibling of the rank IC.

Rank IC answers "did the ordering correlate with returns"; the top-k view
answers "what did holding the best-scored names yield versus holding the
whole cross-section indiscriminately". Same replay discipline (maturity,
dedup, vintage-free display view) over the same per-symbol forward
returns the IC already computes.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import pytest

from app.services.ic_service import evaluate_topk_portfolio
from app.storage.database import AnalysisRecord

pytestmark = pytest.mark.asyncio


def _bdates(n: int) -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in pd.bdate_range(end="2026-09-24", periods=n)]


def _rate_closes(dates: list[str], rate: float) -> list[float]:
    """Compound at ``rate`` per bar from bar 0 — forward returns are ratios,
    so the pre-run path cancels and the per-symbol forward over any window
    is (1 + rate) ** horizon - 1."""
    price = 100.0
    closes: list[float] = []
    for _ in dates:
        price *= 1 + rate
        closes.append(round(price, 6))
    return closes


def _two_epoch_closes(dates: list[str], flip_at: int, rates: tuple[float, float]) -> list[float]:
    """Flat compounding at rates[0] until flip_at, then rates[1] — swapping
    the epoch-2 rate order across symbols flips which symbol wins."""
    price = 100.0
    closes: list[float] = []
    for i in range(len(dates)):
        price *= 1 + rates[i > flip_at]
        closes.append(round(price, 6))
    return closes


def _record(thread_id: str, created_at: str, scored: dict[str, float]) -> AnalysisRecord:
    decisions = {
        symbol: {"symbol": symbol, "action": "hold", "score": score}
        for symbol, score in scored.items()
    }
    return AnalysisRecord(
        thread_id=thread_id,
        symbols="[]",
        query="q",
        status="completed",
        result=json.dumps({"decision": {"decisions": decisions}}),
        created_at=created_at,
        updated_at=created_at,
        execution_time=0.0,
    )


def _fetcher(series: dict[str, tuple[list[str], list[float]]]):
    async def fetch(symbol: str) -> dict[str, Any] | None:
        pair = series.get(symbol)
        return {"dates": pair[0], "close": pair[1]} if pair else None

    return fetch


def _forward(rates: list[float], horizon: int) -> list[float]:
    return [(1 + r) ** horizon - 1 for r in rates]


class TestTopKPortfolio:
    async def test_top1_excess_over_equal_weight_hand_computed(self) -> None:
        """Scores ascending with returns: the top pick must beat the
        equal-weight basket by exactly the hand-computable spread."""
        dates = _bdates(300)
        rates = [0.001, 0.002, 0.003, 0.004]
        series = {sym: (dates, _rate_closes(dates, r)) for sym, r in zip("ABCD", rates)}
        scored = dict(zip("ABCD", (20.0, 40.0, 60.0, 80.0)))
        records = [
            _record("p1", f"{dates[200]}T10:00:00", scored),
            _record("p2", f"{dates[210]}T10:00:00", scored),
        ]

        result = await evaluate_topk_portfolio(
            top_k=1, horizon_bars=20, records=records, fetch_history=_fetcher(series)
        )

        fwd = _forward(rates, 20)
        expected_top = fwd[3]
        expected_baseline = sum(fwd) / 4
        assert result["status"] == "ok"
        assert result["runs_evaluated"] == 2
        assert result["hit_rate"] == 1.0
        assert result["excess_mean"] == pytest.approx(expected_top - expected_baseline)
        run = result["per_run"][0]
        assert run["top_return"] == pytest.approx(expected_top)
        assert run["baseline_return"] == pytest.approx(expected_baseline)
        assert run["excess"] == pytest.approx(expected_top - expected_baseline)

    async def test_reversed_epoch_top_pick_underperforms(self) -> None:
        """Epoch-2 rates swapped across symbols: the best-scored name earns
        the worst forward return — the excess goes negative, the honest
        answer when the ranking is inverted."""
        dates = _bdates(300)
        flip = 239
        series = {
            sym: (dates, _two_epoch_closes(dates, flip, rates))
            for sym, rates in zip(
                "ABCD", ((0.001, 0.004), (0.002, 0.003), (0.003, 0.002), (0.004, 0.001))
            )
        }
        scored = dict(zip("ABCD", (20.0, 40.0, 60.0, 80.0)))
        # One run straddles the flip (its window mixes both epochs), one is
        # fully inside epoch 2 — different excess magnitudes, so the t-stat
        # has genuine dispersion to divide by.
        records = [
            _record("p3", f"{dates[235]}T10:00:00", scored),
            _record("p4", f"{dates[250]}T10:00:00", scored),
        ]

        result = await evaluate_topk_portfolio(
            top_k=1, horizon_bars=20, records=records, fetch_history=_fetcher(series)
        )

        assert result["status"] == "ok"
        assert result["excess_mean"] < 0
        assert result["hit_rate"] == 0.0
        assert result["excess_t_stat"] is not None and result["excess_t_stat"] < 0

    async def test_narrow_cross_section_is_skipped_not_stretched(self) -> None:
        """k = n means the "pick" IS the market — no ranking edge exists to
        measure, so the run tallies narrow rather than fabricating a zero
        excess."""
        dates = _bdates(300)
        rates = [0.001, 0.002, 0.003]
        series = {sym: (dates, _rate_closes(dates, r)) for sym, r in zip("ABC", rates)}
        scored = dict(zip("ABC", (20.0, 60.0, 80.0)))
        records = [_record("p5", f"{dates[200]}T10:00:00", scored)]

        result = await evaluate_topk_portfolio(
            top_k=3, horizon_bars=20, records=records, fetch_history=_fetcher(series)
        )

        assert result["status"] == "insufficient_history"
        assert result["runs_narrow"] == 1
        assert result["runs_evaluated"] == 0

    async def test_duplicate_records_collapse_to_one_run(self) -> None:
        dates = _bdates(300)
        rates = [0.001, 0.002, 0.003, 0.004]
        series = {sym: (dates, _rate_closes(dates, r)) for sym, r in zip("ABCD", rates)}
        scored = dict(zip("ABCD", (20.0, 40.0, 60.0, 80.0)))
        records = [
            _record("p6", f"{dates[200]}T10:00:00", scored),
            _record("p7", f"{dates[200]}T14:00:00", scored),
        ]

        result = await evaluate_topk_portfolio(
            top_k=1, horizon_bars=20, records=records, fetch_history=_fetcher(series)
        )

        assert result["runs_duplicate"] == 1
        assert result["runs_evaluated"] == 1

    async def test_pending_maturity_tallied(self) -> None:
        dates = _bdates(300)
        rates = [0.001, 0.002, 0.003, 0.004]
        series = {sym: (dates, _rate_closes(dates, r)) for sym, r in zip("ABCD", rates)}
        scored = dict(zip("ABCD", (20.0, 40.0, 60.0, 80.0)))
        records = [_record("p8", f"{dates[-1]}T10:00:00", scored)]

        result = await evaluate_topk_portfolio(
            top_k=1, horizon_bars=20, records=records, fetch_history=_fetcher(series)
        )

        assert result["status"] == "insufficient_history"
        assert result["runs_pending_maturity"] == 1
        assert result["runs_evaluated"] == 0

    async def test_validation_rejects_nonpositive_arguments(self) -> None:
        with pytest.raises(ValueError, match="horizon_bars must be positive"):
            await evaluate_topk_portfolio(top_k=1, horizon_bars=0, records=[], fetch_history=None)
        with pytest.raises(ValueError, match="top_k must be positive"):
            await evaluate_topk_portfolio(top_k=0, horizon_bars=20, records=[], fetch_history=None)
