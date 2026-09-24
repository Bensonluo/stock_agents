"""Decision-layer IC replay over stored history (offline, injected fetcher)."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import pytest

from app.services.ic_service import evaluate_decision_ic
from app.storage.database import AnalysisRecord

pytestmark = pytest.mark.asyncio


def _bdates(n: int) -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in pd.bdate_range(end="2026-09-24", periods=n)]


def _two_phase_closes(
    dates: list[str], idx1: int, rate1: float, idx2: int | None = None, rate2: float = 0.0
) -> list[float]:
    """Flat 100 until idx1, grows at rate1/bar until idx2, then at rate2/bar —
    the ordering of forward returns can differ across epochs."""
    price = 100.0
    closes: list[float] = []
    for i in range(len(dates)):
        if idx2 is not None and i > idx2:
            price *= 1 + rate2
        elif i > idx1:
            price *= 1 + rate1
        closes.append(round(price, 6))
    return closes


def _record(thread_id: str, created_at: str, scored: dict[str, float | None]) -> AnalysisRecord:
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


def _fetcher(series: dict[str, tuple[list[str], list[float]]], calls: list[str] | None = None):
    async def fetch(symbol: str) -> dict[str, Any] | None:
        if calls is not None:
            calls.append(symbol)
        pair = series.get(symbol)
        if pair is None:
            return None
        return {"dates": pair[0], "close": pair[1]}

    return fetch


class TestEvaluateDecisionIC:
    async def test_perfectly_ordered_run_scores_ic_one(self) -> None:
        dates = _bdates(300)
        run_idx = 239  # 60 mature bars after the run date
        series = {
            sym: (dates, _two_phase_closes(dates, run_idx, rate))
            for sym, rate in zip("ABCD", (0.001, 0.002, 0.003, 0.004))
        }
        record = _record(
            "t1", f"{dates[run_idx]}T10:00:00", dict(zip("ABCD", (20.0, 40.0, 60.0, 80.0)))
        )
        result = await evaluate_decision_ic(
            horizon_bars=20, records=[record], fetch_history=_fetcher(series)
        )
        assert result["status"] == "ok"
        assert result["runs_evaluated"] == 1
        assert result["ic_mean"] == 1.0
        assert result["per_run"][0]["ic"] == 1.0
        assert result["per_run"][0]["symbols"] == 4
        # A single run has a mean but no estimable dispersion.
        assert result["icir"] is None

    async def test_two_runs_aggregate_with_one_symbol_fetch_each(self) -> None:
        dates = _bdates(300)
        idx1, idx2 = 200, 239  # run1's 20-bar window matures before run2 starts
        calls: list[str] = []
        series = {}
        for sym, (r1, r2) in zip(
            "ABCD", ((0.001, 0.004), (0.002, 0.003), (0.003, 0.002), (0.004, 0.001))
        ):
            series[sym] = (dates, _two_phase_closes(dates, idx1, r1, idx2, r2))
        scored = dict(zip("ABCD", (20.0, 40.0, 60.0, 80.0)))
        records = [
            _record("t1", f"{dates[idx1]}T10:00:00", scored),
            _record("t2", f"{dates[idx2]}T10:00:00", scored),
        ]
        result = await evaluate_decision_ic(
            horizon_bars=20, records=records, fetch_history=_fetcher(series, calls)
        )
        assert result["status"] == "ok"
        # Epoch 1 aligned with the scores, epoch 2 reversed: ics = {+1, -1}.
        assert sorted(r["ic"] for r in result["per_run"]) == [-1.0, 1.0]
        assert result["runs"] == 2
        assert result["ic_mean"] == 0.0
        assert result["icir"] == 0.0
        # The full history is fetched once per symbol regardless of run count.
        assert sorted(calls) == ["A", "B", "C", "D"]

    async def test_immature_run_is_pending_not_evaluated(self) -> None:
        dates = _bdates(300)
        run_date = dates[-2]  # one bar of forward data — window of 20 cannot mature
        series = {sym: (dates, _two_phase_closes(dates, len(dates) - 2, 0.001)) for sym in "ABC"}
        record = _record("t3", f"{run_date}T10:00:00", dict(zip("ABC", (20.0, 50.0, 80.0))))
        result = await evaluate_decision_ic(
            horizon_bars=20, records=[record], fetch_history=_fetcher(series)
        )
        assert result["runs_pending_maturity"] == 1
        assert result["runs_evaluated"] == 0
        assert result["status"] == "insufficient_history"

    async def test_dead_symbol_shrinks_the_cross_section(self) -> None:
        dates = _bdates(300)
        run_idx = 250
        # Only A and B have retrievable history; C's fetch returns None.
        series = {
            sym: (dates, _two_phase_closes(dates, run_idx, rate))
            for sym, rate in zip("AB", (0.001, 0.002))
        }
        record = _record("t4", f"{dates[run_idx]}T10:00:00", dict(zip("ABC", (20.0, 50.0, 80.0))))
        result = await evaluate_decision_ic(
            horizon_bars=20, records=[record], fetch_history=_fetcher(series)
        )
        # Two survivors cannot form a rank correlation — the run is skipped,
        # never evaluated on a silently truncated cross-section.
        assert result["runs_skipped"] == 1
        assert result["runs_evaluated"] == 0
        assert result["status"] == "insufficient_history"

    async def test_unparseable_result_is_skipped(self) -> None:
        record = AnalysisRecord(
            thread_id="t5",
            symbols="[]",
            query="q",
            status="completed",
            result="not-json",
            created_at="2026-01-15T10:00:00",
            updated_at="2026-01-15T10:00:00",
            execution_time=0.0,
        )
        result = await evaluate_decision_ic(
            horizon_bars=20, records=[record], fetch_history=_fetcher({})
        )
        assert result["runs_skipped"] == 1
        assert result["status"] == "insufficient_history"

    async def test_horizon_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="horizon"):
            await evaluate_decision_ic(horizon_bars=0, records=[], fetch_history=_fetcher({}))
