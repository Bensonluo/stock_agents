"""Unit tests for the shared bounded-store eviction policy."""

import pytest

from app.utils.bounded_store import evict_oldest_terminal

pytestmark = pytest.mark.asyncio


def _entry(status: str, updated_at: str = "") -> dict:
    return {"status": status, "updated_at": updated_at}


class TestEvictOldestTerminal:
    async def test_under_capacity_is_noop(self):
        store = {"a": _entry("running")}
        assert evict_oldest_terminal(store, 10) is None
        assert list(store) == ["a"]

    async def test_evicts_oldest_terminal_first(self):
        store = {
            "old-done": _entry("completed", "2026-01-01T00:00:00"),
            "new-done": _entry("failed", "2026-02-01T00:00:00"),
            "live": _entry("running", "2026-03-01T00:00:00"),
        }
        assert evict_oldest_terminal(store, 3) == "old-done"
        assert "old-done" not in store
        assert "live" in store  # running entries survive while terminals exist

    async def test_all_live_falls_back_to_oldest(self):
        store = {
            "b": _entry("running", "2026-02-01"),
            "a": _entry("running", "2026-01-01"),
        }
        assert evict_oldest_terminal(store, 2) == "a"

    async def test_custom_terminal_statuses(self):
        store = {
            "partial": _entry("partial", "2026-01-01"),
            "running": _entry("running", "2026-03-01"),
        }
        assert evict_oldest_terminal(store, 2, terminal_statuses=("partial",)) == "partial"

    async def test_custom_timestamp_and_on_evict_cleanup(self):
        store = {"x": {"status": "completed"}, "y": {"status": "completed"}}
        logs = {"x": [1, 2], "y": [3]}
        evicted = evict_oldest_terminal(
            store,
            2,
            timestamp_of=lambda e: 1 if e is store["y"] else 0,  # x sorts oldest
            on_evict=logs.pop,
        )
        assert evicted == "x"
        assert "x" not in logs and "y" in logs

    async def test_missing_timestamp_sorts_oldest(self):
        store = {
            "no-ts": _entry("completed"),
            "with-ts": _entry("completed", "2026-01-01"),
        }
        assert evict_oldest_terminal(store, 2) == "no-ts"
