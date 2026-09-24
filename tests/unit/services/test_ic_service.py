"""Decision-layer IC replay over stored history (offline, injected fetcher)."""

from __future__ import annotations

import json
from time import monotonic
from typing import Any

import pandas as pd
import pytest

import app.services.ic_service as ic_service_module
from app.services.ic_service import (
    REPLAY_SERIES_TTL,
    evaluate_confidence_calibration,
    evaluate_decision_ic,
    evaluate_ic_decay,
)
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


def _claim_record(
    thread_id: str, created_at: str, actions: dict[str, tuple[str, float]]
) -> AnalysisRecord:
    decisions = {
        symbol: {"symbol": symbol, "action": action, "confidence": confidence}
        for symbol, (action, confidence) in actions.items()
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

    async def test_dimension_attribution_splits_aligned_and_inverted(self) -> None:
        dates = _bdates(300)
        run_idx = 239
        series = {
            sym: (dates, _two_phase_closes(dates, run_idx, rate))
            for sym, rate in zip("ABCD", (0.001, 0.002, 0.003, 0.004))
        }
        scored = dict(zip("ABCD", (20.0, 42.0, 61.0, 83.0)))
        decisions = {
            sym: {
                "symbol": sym,
                "action": "hold",
                "score": score,
                "component_scores": {
                    "technical": score,  # aligned with the forward ordering
                    "fundamental": 100.0 - score,  # inverted
                    "sentiment": 50.0,  # rank-constant -> refused
                },
            }
            for sym, score in scored.items()
        }
        record = AnalysisRecord(
            thread_id="t6",
            symbols="[]",
            query="q",
            status="completed",
            result=json.dumps({"decision": {"decisions": decisions}}),
            created_at=f"{dates[run_idx]}T10:00:00",
            updated_at=f"{dates[run_idx]}T10:00:00",
            execution_time=0.0,
        )
        result = await evaluate_decision_ic(
            horizon_bars=20, records=[record], fetch_history=_fetcher(series)
        )
        dimensions = result["dimensions"]
        assert dimensions["technical"]["ic_mean"] == 1.0
        assert dimensions["fundamental"]["ic_mean"] == -1.0
        # Rank-constant input is refused rather than fabricated as zero —
        # the dimension simply never accumulates an IC.
        assert "sentiment" not in dimensions

    async def test_dimensions_absent_for_legacy_runs(self) -> None:
        # Records stored before component tracking have no component_scores;
        # the composite IC still evaluates, dimensions stay empty.
        dates = _bdates(300)
        run_idx = 239
        series = {
            sym: (dates, _two_phase_closes(dates, run_idx, rate))
            for sym, rate in zip("ABCD", (0.001, 0.002, 0.003, 0.004))
        }
        record = _record(
            "t7", f"{dates[run_idx]}T10:00:00", dict(zip("ABCD", (20.0, 40.0, 60.0, 80.0)))
        )
        result = await evaluate_decision_ic(
            horizon_bars=20, records=[record], fetch_history=_fetcher(series)
        )
        assert result["status"] == "ok"
        assert result["dimensions"] == {}

    async def test_decay_maturity_is_per_horizon(self) -> None:
        dates = _bdates(300)
        run_idx = 245  # 54 mature bars after the run date
        series = {
            sym: (dates, _two_phase_closes(dates, run_idx, rate))
            for sym, rate in zip("ABCD", (0.001, 0.002, 0.003, 0.004))
        }
        record = _record(
            "t8", f"{dates[run_idx]}T10:00:00", dict(zip("ABCD", (20.0, 40.0, 60.0, 80.0)))
        )
        result = await evaluate_ic_decay(
            horizons=[5, 10, 60], records=[record], fetch_history=_fetcher(series)
        )
        points = {p["horizon_bars"]: p for p in result["horizons"]}
        # 5 and 10 bars mature; 60 does not — the same run is evaluated at
        # short horizons and pending at the long one.
        assert points[5]["status"] == "ok"
        assert points[5]["ic_mean"] == 1.0
        assert points[10]["status"] == "ok"
        assert points[60]["runs_pending_maturity"] == 1
        assert points[60]["status"] == "insufficient_history"
        assert result["status"] == "ok"

    async def test_decay_fetches_each_symbol_once_across_horizons(self) -> None:
        dates = _bdates(300)
        run_idx = 239
        calls: list[str] = []
        series = {
            sym: (dates, _two_phase_closes(dates, run_idx, rate))
            for sym, rate in zip("ABCD", (0.001, 0.002, 0.003, 0.004))
        }
        record = _record(
            "t9", f"{dates[run_idx]}T10:00:00", dict(zip("ABCD", (20.0, 40.0, 60.0, 80.0)))
        )
        await evaluate_ic_decay(
            horizons=[5, 10, 20, 60],
            records=[record],
            fetch_history=_fetcher(series, calls),
        )
        # One pass, one fetch per unique symbol — regardless of horizon count.
        assert sorted(calls) == ["A", "B", "C", "D"]

    async def test_decay_rejects_invalid_horizons(self) -> None:
        with pytest.raises(ValueError, match="horizons"):
            await evaluate_ic_decay(horizons=[], records=[], fetch_history=_fetcher({}))
        with pytest.raises(ValueError, match="horizons"):
            await evaluate_ic_decay(horizons=[0, 20], records=[], fetch_history=_fetcher({}))
        with pytest.raises(ValueError, match="horizons"):
            await evaluate_ic_decay(
                horizons=[5, 10, 20, 60, 120, 200, 250],
                records=[],
                fetch_history=_fetcher({}),
            )


class TestConfidenceCalibration:
    async def test_all_correct_buys_hand_computed(self) -> None:
        dates = _bdates(300)
        run_idx = 239
        series = {
            sym: (dates, _two_phase_closes(dates, run_idx, rate))
            for sym, rate in zip("AB", (0.001, 0.002))
        }
        record = _claim_record(
            "c1", f"{dates[run_idx]}T10:00:00", {"A": ("buy", 0.8), "B": ("buy", 0.6)}
        )
        result = await evaluate_confidence_calibration(
            horizon_bars=20, records=[record], fetch_history=_fetcher(series)
        )
        assert result["status"] == "ok"
        assert result["predictions"] == 2
        assert result["runs_evaluated"] == 1
        assert result["base_rate"] == 1.0
        # (1-0.8)^2 + (1-0.6)^2 = 0.04 + 0.16, over 2 -> 0.1
        assert result["brier_score"] == 0.1
        # Constant outcomes: the base-rate forecaster is unbeatable there,
        # so skill is undefined rather than infinite.
        assert result["brier_skill_score"] is None
        assert result["avg_confidence"] == 0.7

    async def test_mixed_directions_hand_computed(self) -> None:
        dates = _bdates(300)
        run_idx = 239
        # Both series rise: the buy claim is vindicated, the sell claim fails.
        series = {
            sym: (dates, _two_phase_closes(dates, run_idx, rate))
            for sym, rate in zip("AB", (0.001, 0.002))
        }
        record = _claim_record(
            "c2", f"{dates[run_idx]}T10:00:00", {"A": ("buy", 0.8), "B": ("sell", 0.7)}
        )
        result = await evaluate_confidence_calibration(
            horizon_bars=20, records=[record], fetch_history=_fetcher(series)
        )
        assert result["base_rate"] == 0.5
        # (1-0.8)^2 + (0-0.7)^2 = 0.04 + 0.49, over 2 -> 0.265
        assert result["brier_score"] == 0.265
        # 1 - 0.265/0.25 = -0.06: worse than always guessing the base rate.
        assert result["brier_skill_score"] == -0.06
        buckets = {b["bin_low"]: b for b in result["reliability"]}
        assert buckets[0.6]["empirical_rate"] == 0.0  # the failed sell
        assert buckets[0.8]["empirical_rate"] == 1.0  # the vindicated buy

    async def test_single_symbol_claim_evaluates_without_cross_section(self) -> None:
        # The IC replay needs >= 3 symbols to rank; a single directional
        # claim is one probabilistic prediction and calibrates on its own.
        dates = _bdates(300)
        run_idx = 239
        series = {"A": (dates, _two_phase_closes(dates, run_idx, 0.001))}
        record = _claim_record("c3", f"{dates[run_idx]}T10:00:00", {"A": ("buy", 0.75)})
        result = await evaluate_confidence_calibration(
            horizon_bars=20, records=[record], fetch_history=_fetcher(series)
        )
        assert result["status"] == "ok"
        assert result["predictions"] == 1
        assert result["runs_evaluated"] == 1

    async def test_hold_only_run_makes_no_claims(self) -> None:
        dates = _bdates(300)
        run_idx = 239
        series = {"A": (dates, _two_phase_closes(dates, run_idx, 0.001))}
        record = _claim_record("c4", f"{dates[run_idx]}T10:00:00", {"A": ("hold", 0.9)})
        result = await evaluate_confidence_calibration(
            horizon_bars=20, records=[record], fetch_history=_fetcher(series)
        )
        assert result["status"] == "insufficient_history"
        assert result["predictions"] == 0
        assert result["runs_skipped"] == 1

    async def test_immature_claim_is_pending(self) -> None:
        dates = _bdates(300)
        run_date = dates[-2]  # one bar of forward data — 20-bar window cannot mature
        series = {"A": (dates, _two_phase_closes(dates, len(dates) - 2, 0.001))}
        record = _claim_record("c5", f"{run_date}T10:00:00", {"A": ("buy", 0.8)})
        result = await evaluate_confidence_calibration(
            horizon_bars=20, records=[record], fetch_history=_fetcher(series)
        )
        assert result["status"] == "insufficient_history"
        assert result["runs_pending_maturity"] == 1
        assert result["predictions"] == 0

    async def test_dead_symbol_claim_drops_out(self) -> None:
        dates = _bdates(300)
        record = _claim_record("c6", f"{dates[239]}T10:00:00", {"A": ("buy", 0.8)})
        result = await evaluate_confidence_calibration(
            horizon_bars=20, records=[record], fetch_history=_fetcher({})
        )
        assert result["status"] == "insufficient_history"
        assert result["runs_skipped"] == 1
        assert result["predictions"] == 0

    async def test_horizon_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="horizon"):
            await evaluate_confidence_calibration(
                horizon_bars=0, records=[], fetch_history=_fetcher({})
            )


class TestReplaySeriesCache:
    """Production-path caching over the shared fetcher — daily data needs
    no per-view freshness, but failures must never be remembered."""

    @pytest.fixture(autouse=True)
    def _clean_cache(self):
        ic_service_module._replay_cache.clear()
        yield
        ic_service_module._replay_cache.clear()

    async def test_second_call_hits_the_cache(self, monkeypatch) -> None:
        calls: list[tuple[str, str]] = []

        async def fake_fetch(symbol: str, period: str) -> dict[str, Any]:
            calls.append((symbol, period))
            return {"dates": ["2026-01-01"], "close": [100.0]}

        monkeypatch.setattr(ic_service_module, "fetch_historical", fake_fetch)
        first = await ic_service_module._cached_default_fetch("AAPL")
        second = await ic_service_module._cached_default_fetch("AAPL")
        assert first is second  # same object — a hit, not a refetch
        assert calls == [("AAPL", "5y")]

    async def test_expired_entry_refetches(self, monkeypatch) -> None:
        calls: list[str] = []

        async def fake_fetch(symbol: str, period: str) -> dict[str, Any]:
            calls.append(symbol)
            return {"dates": ["2026-01-01"], "close": [100.0]}

        monkeypatch.setattr(ic_service_module, "fetch_historical", fake_fetch)
        ic_service_module._replay_cache["AAPL"] = (
            monotonic() - (REPLAY_SERIES_TTL + 1),
            {"dates": ["2025-01-01"], "close": [50.0]},
        )
        data = await ic_service_module._cached_default_fetch("AAPL")
        assert calls == ["AAPL"]  # stale entry discarded, refetched
        assert data["dates"] == ["2026-01-01"]

    async def test_failure_is_never_cached(self, monkeypatch) -> None:
        calls: list[str] = []

        async def fake_fetch(symbol: str, period: str) -> dict[str, Any] | None:
            calls.append(symbol)
            return None

        monkeypatch.setattr(ic_service_module, "fetch_historical", fake_fetch)
        assert await ic_service_module._cached_default_fetch("AAPL") is None
        assert await ic_service_module._cached_default_fetch("AAPL") is None
        # A transient outage must not poison 30 minutes of replays.
        assert calls == ["AAPL", "AAPL"]
        assert "AAPL" not in ic_service_module._replay_cache

    async def test_injected_fetchers_bypass_the_cache(self) -> None:
        # records provided + no fetcher -> pass-through default; the caching
        # path engages only on the production (DB) branch, so test doubles
        # can never leak results across tests through the global cache.
        records, fetcher = ic_service_module._resolve_inputs([], 10, None)
        assert records == []
        assert fetcher is not ic_service_module._cached_default_fetch
