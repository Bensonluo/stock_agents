"""Regime-conditional IC — does the ranking skill depend on the market regime?

Mirrors the decay-view fixtures: synthetic two-epoch histories where epoch 1
aligns forward-return ordering with the scores (IC +1) and epoch 2 reverses
it (IC -1). Labeling the runs with regimes splits the same evidence the
aggregate view averages over: bull-epoch runs land in the bull bin with a
positive IC, bear-epoch runs in the bear bin with a negative one.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import pytest

from app.services.ic_service import (
    evaluate_decision_ic,
    evaluate_regime_conditional_ic,
)
from app.storage.database import AnalysisRecord

pytestmark = pytest.mark.asyncio

_BULL = {"status": "ok", "bars": 300, "trend": "bull", "price_vs_sma200": 0.064}
_BEAR = {"status": "ok", "bars": 300, "trend": "bear", "price_vs_sma200": -0.084}


def _bdates(n: int) -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in pd.bdate_range(end="2026-09-24", periods=n)]


def _two_epoch_closes(dates: list[str], flip_at: int, rates: tuple[float, float]) -> list[float]:
    """Flat compounding at each symbol's epoch-1 rate until flip_at, then the
    epoch-2 rate — assign descending epoch-2 rates to ascending epoch-1 rates
    and the two epochs order forward returns oppositely (IC +1 then -1)."""
    price = 100.0
    closes: list[float] = []
    for i in range(len(dates)):
        rate = rates[i > flip_at]
        price *= 1 + rate
        closes.append(round(price, 6))
    return closes


def _record(
    thread_id: str,
    created_at: str,
    scored: dict[str, float],
    regime: dict | None,
) -> AnalysisRecord:
    decisions = {
        symbol: {"symbol": symbol, "action": "hold", "score": score}
        for symbol, score in scored.items()
    }
    result: dict[str, Any] = {"decision": {"decisions": decisions}}
    if regime is not None:
        result["risk_assessment"] = {"risk_by_symbol": {}, "market_regime": regime}
    return AnalysisRecord(
        thread_id=thread_id,
        symbols="[]",
        query="q",
        status="completed",
        result=json.dumps(result),
        created_at=created_at,
        updated_at=created_at,
        execution_time=0.0,
    )


def _fetcher(series: dict[str, tuple[list[str], list[float]]]):
    async def fetch(symbol: str) -> dict[str, Any] | None:
        pair = series.get(symbol)
        return {"dates": pair[0], "close": pair[1]} if pair else None

    return fetch


def _labeled_fixture() -> tuple[list[AnalysisRecord], Any]:
    """Two bull runs inside the aligned epoch (+1 IC each) and two bear runs
    inside the reversed epoch (-1 IC each)."""
    dates = _bdates(300)
    flip = 239  # epoch 1: bars 0..239, epoch 2: 240..299
    series = {
        sym: (dates, _two_epoch_closes(dates, flip, rates))
        for sym, rates in zip(
            "ABCD", ((0.001, 0.004), (0.002, 0.003), (0.003, 0.002), (0.004, 0.001))
        )
    }
    scored = dict(zip("ABCD", (20.0, 40.0, 60.0, 80.0)))
    records = [
        _record("bull-1", f"{dates[200]}T10:00:00", scored, _BULL),
        _record("bull-2", f"{dates[210]}T10:00:00", scored, _BULL),
        _record("bear-1", f"{dates[240]}T10:00:00", scored, _BEAR),
        _record("bear-2", f"{dates[250]}T10:00:00", scored, _BEAR),
    ]
    return records, _fetcher(series)


class TestRegimeConditionalIC:
    async def test_bull_bin_positive_bear_bin_negative(self) -> None:
        records, fetcher = _labeled_fixture()

        result = await evaluate_regime_conditional_ic(
            horizon_bars=20, records=records, fetch_history=fetcher
        )

        assert result["status"] == "ok"
        assert result["runs_evaluated"] == 4
        bull, bear = result["regimes"]["bull"], result["regimes"]["bear"]
        assert bull["status"] == "ok" and bull["runs"] == 2 and bull["ic_mean"] == 1.0
        assert bear["status"] == "ok" and bear["runs"] == 2 and bear["ic_mean"] == -1.0
        # Empty bins are honestly insufficient, not fabricated.
        assert result["regimes"]["neutral"]["status"] == "insufficient_history"
        assert result["regimes"]["neutral"]["runs"] == 0
        assert result["regimes"]["unknown"]["runs"] == 0

    async def test_unlabeled_runs_bin_as_unknown(self) -> None:
        records, fetcher = _labeled_fixture()
        dates = _bdates(300)
        scored = dict(zip("ABCD", (20.0, 40.0, 60.0, 80.0)))
        records.append(_record("legacy", f"{dates[220]}T10:00:00", scored, None))

        result = await evaluate_regime_conditional_ic(
            horizon_bars=20, records=records, fetch_history=fetcher
        )

        unknown = result["regimes"]["unknown"]
        assert unknown["runs"] == 1
        # A single run in a bin keeps its mean but is not "ok" evidence.
        assert unknown["status"] == "insufficient_history"
        assert unknown["ic_mean"] == 1.0
        assert result["regimes"]["bull"]["runs"] == 2

    async def test_pre_regime_history_never_fabricates_measured_bins(self) -> None:
        dates = _bdates(300)
        flip = 239
        series = {
            sym: (dates, _two_epoch_closes(dates, flip, rates))
            for sym, rates in zip(
                "ABCD", ((0.001, 0.004), (0.002, 0.003), (0.003, 0.002), (0.004, 0.001))
            )
        }
        scored = dict(zip("ABCD", (20.0, 40.0, 60.0, 80.0)))
        records = [
            _record("t1", f"{dates[200]}T10:00:00", scored, None),
            _record("t2", f"{dates[240]}T10:00:00", scored, None),
        ]

        result = await evaluate_regime_conditional_ic(
            horizon_bars=20, records=records, fetch_history=_fetcher(series)
        )

        # Unknown IS a measurable bin — evidence exists, it is just
        # unlabeled — so it can carry an "ok" verdict of its own. The
        # MEASURED bins stay honestly empty rather than absorbing the
        # unlabeled runs as fake neutrals.
        assert result["regimes"]["unknown"]["runs"] == 2
        assert result["regimes"]["unknown"]["status"] == "ok"
        assert result["status"] == "ok"  # the unknown bin alone carries it
        for name in ("bull", "bear", "neutral"):
            assert result["regimes"][name]["runs"] == 0
            assert result["regimes"][name]["status"] == "insufficient_history"

    async def test_per_run_rows_carry_their_regime_trend(self) -> None:
        records, fetcher = _labeled_fixture()

        result = await evaluate_decision_ic(horizon_bars=20, records=records, fetch_history=fetcher)

        by_thread = {r["thread_id"]: r for r in result["per_run"]}
        assert by_thread["bull-1"]["regime_trend"] == "bull"
        assert by_thread["bear-1"]["regime_trend"] == "bear"

    async def test_horizon_validation_rejects_nonpositive(self) -> None:
        with pytest.raises(ValueError, match="horizon_bars must be positive"):
            await evaluate_regime_conditional_ic(horizon_bars=0, records=[], fetch_history=None)
