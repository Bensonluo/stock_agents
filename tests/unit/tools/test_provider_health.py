"""Provider health counters: pure in-process outcome accounting.

The data-source chain's provider outcomes (ok / fail / fallback) were
previously invisible outside the logs — the 2026-09 East Money block and
the multi-day Yahoo 429 stretch were only discoverable by log archaeology.
These tests pin the counter contract itself: counts, recency timestamps,
snapshot shape, detail truncation, reset, and thread safety (the fetcher's
sync seams run inside asyncio.to_thread workers, so records arrive from
many threads at once). Pure offline unit tests — no fetcher, no network.
"""

from __future__ import annotations

import threading
from datetime import datetime

import pytest

from app.tools.data.provider_health import (
    provider_health_snapshot,
    record_provider_outcome,
    reset_provider_health,
)


@pytest.fixture(autouse=True)
def _isolated_counters():
    reset_provider_health()
    yield
    reset_provider_health()


class TestRecordAndSnapshot:
    def test_ok_fail_fallback_counts_accumulate_per_provider(self) -> None:
        record_provider_outcome("alpha", "ok")
        record_provider_outcome("alpha", "ok")
        record_provider_outcome("alpha", "fail", "boom")
        record_provider_outcome("beta", "fallback", "primary dead, backup caught")

        snap = provider_health_snapshot()["providers"]

        assert snap["alpha"]["total_calls"] == 3
        assert snap["alpha"]["ok"] == 2
        assert snap["alpha"]["fail"] == 1
        assert snap["alpha"]["fallback"] == 0
        assert snap["beta"]["total_calls"] == 1
        assert snap["beta"]["fallback"] == 1
        assert snap["beta"]["ok"] == 0
        assert snap["beta"]["fail"] == 0

    def test_snapshot_shape_has_every_documented_field(self) -> None:
        record_provider_outcome("alpha", "ok")
        snap = provider_health_snapshot()

        assert set(snap) == {"providers", "generated_at"}
        assert set(snap["providers"]["alpha"]) == {
            "total_calls",
            "ok",
            "fail",
            "fallback",
            "last_ok_at",
            "last_error",
            "last_error_at",
        }

    def test_last_ok_and_error_timestamps_are_iso(self) -> None:
        record_provider_outcome("alpha", "fail", "ConnectionError: drop")
        record_provider_outcome("alpha", "ok")

        state = provider_health_snapshot()["providers"]["alpha"]
        assert datetime.fromisoformat(state["last_ok_at"])
        assert datetime.fromisoformat(state["last_error_at"])
        assert state["last_error"] == "ConnectionError: drop"

    def test_ok_never_touches_error_fields(self) -> None:
        record_provider_outcome("alpha", "ok")

        state = provider_health_snapshot()["providers"]["alpha"]
        assert state["last_error"] is None
        assert state["last_error_at"] is None

    def test_fail_without_detail_keeps_the_previous_error_summary(self) -> None:
        record_provider_outcome("alpha", "fail", "first failure")
        record_provider_outcome("alpha", "fail")

        state = provider_health_snapshot()["providers"]["alpha"]
        assert state["fail"] == 2
        assert state["last_error"] == "first failure"

    def test_fallback_marks_both_the_save_and_the_degradation(self) -> None:
        """outcome=fallback means "primary dead, fallback caught" — data was
        served (last_ok_at) AND the primary died (last_error*), so both
        recency fields move."""
        record_provider_outcome("em", "fallback", "EM blocked; tencent caught")

        state = provider_health_snapshot()["providers"]["em"]
        assert state["fallback"] == 1
        assert state["last_ok_at"] is not None
        assert state["last_error"] == "EM blocked; tencent caught"
        assert state["last_error_at"] is not None

    def test_detail_truncated_to_200_chars(self) -> None:
        record_provider_outcome("alpha", "fail", "x" * 500)

        state = provider_health_snapshot()["providers"]["alpha"]
        assert len(state["last_error"]) == 200

    def test_detail_newlines_collapse_to_one_line(self) -> None:
        """No stack dump may leak through the detail — one line, bounded."""
        record_provider_outcome(
            "alpha", "fail", 'Traceback (most recent call last):\n  File "x", line 1\nBoom'
        )

        state = provider_health_snapshot()["providers"]["alpha"]
        assert "\n" not in state["last_error"]
        assert "Boom" in state["last_error"]

    def test_unknown_outcome_is_ignored_entirely(self) -> None:
        """A bad outcome must never fabricate a count — and never raise."""
        record_provider_outcome("alpha", "exploded")
        record_provider_outcome("", "ok")

        assert provider_health_snapshot()["providers"] == {}

    def test_empty_snapshot_has_no_providers_but_keeps_shape(self) -> None:
        snap = provider_health_snapshot()

        assert snap["providers"] == {}
        assert datetime.fromisoformat(snap["generated_at"])

    def test_snapshot_is_a_copy_not_live_state(self) -> None:
        record_provider_outcome("alpha", "ok")
        snap = provider_health_snapshot()
        snap["providers"]["alpha"]["ok"] = 999

        assert provider_health_snapshot()["providers"]["alpha"]["ok"] == 1


class TestReset:
    def test_reset_clears_every_provider(self) -> None:
        record_provider_outcome("alpha", "ok")
        record_provider_outcome("beta", "fail", "x")
        reset_provider_health()

        assert provider_health_snapshot()["providers"] == {}


class TestConcurrency:
    def test_concurrent_records_lose_no_counts(self) -> None:
        """100 records from 10 threads must land exactly. The fetcher's sync
        seams run inside asyncio.to_thread workers, so concurrent record
        calls are the production shape, not an edge case — dict read-modify-
        write is not atomic even under the GIL."""
        barrier = threading.Barrier(10)

        def _hammer() -> None:
            barrier.wait()  # maximize overlap on the first record
            for _ in range(5):
                record_provider_outcome("shared", "ok")
                record_provider_outcome("shared", "fail", "boom")

        threads = [threading.Thread(target=_hammer) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        state = provider_health_snapshot()["providers"]["shared"]
        assert state["total_calls"] == 100
        assert state["ok"] == 50
        assert state["fail"] == 50
