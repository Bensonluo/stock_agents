"""Tests for the durable SQLite checkpoint manager."""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import StateGraph
from typing_extensions import TypedDict

from app.orchestration.checkpoint import SqliteCheckpointManager

pytestmark = pytest.mark.asyncio


class _S(TypedDict):
    count: int


def _build_graph():
    g = StateGraph(_S)
    g.add_node("add", lambda s: {"count": s["count"] + 1})
    g.set_entry_point("add")
    g.set_finish_point("add")
    return g


class TestSqliteCheckpointManager:
    async def test_saver_roundtrip_and_durability(self, tmp_path):
        db = str(tmp_path / "ck.db")
        manager = SqliteCheckpointManager(db_path=db)

        graph = _build_graph().compile(checkpointer=manager.get_checkpoint_saver())
        result = await graph.ainvoke({"count": 1}, {"configurable": {"thread_id": "t1"}})
        assert result["count"] == 2
        assert isinstance(manager.get_checkpoint_saver(), AsyncSqliteSaver)
        await manager.aclose()

        # A fresh manager on the same file sees the persisted state.
        manager2 = SqliteCheckpointManager(db_path=db)
        graph2 = _build_graph().compile(checkpointer=manager2.get_checkpoint_saver())
        snap = await graph2.aget_state({"configurable": {"thread_id": "t1"}})
        assert snap.values["count"] == 2
        await manager2.aclose()

    async def test_aload_state_reads_channel_values(self, tmp_path):
        manager = SqliteCheckpointManager(db_path=str(tmp_path / "ck.db"))
        graph = _build_graph().compile(checkpointer=manager.get_checkpoint_saver())
        await graph.ainvoke({"count": 41}, {"configurable": {"thread_id": "t9"}})

        state = await manager.aload_state("t9")
        assert state is not None
        assert state.get("count") == 42
        assert await manager.aload_state("no-such-thread") is None
        await manager.aclose()

    async def test_unknown_thread_returns_none(self, tmp_path):
        manager = SqliteCheckpointManager(db_path=str(tmp_path / "ck.db"))
        graph = _build_graph().compile(checkpointer=manager.get_checkpoint_saver())
        await graph.ainvoke({"count": 1}, {"configurable": {"thread_id": "live"}})
        assert await manager.aload_state("ghost") is None
        await manager.aclose()

    def test_no_running_loop_degrades_to_memory_saver(self, tmp_path):
        manager = SqliteCheckpointManager(db_path=str(tmp_path / "ck.db"))
        saver = manager.get_checkpoint_saver()  # sync context: no event loop
        assert isinstance(saver, InMemorySaver)


class TestBackendSelection:
    def test_explicit_sqlite_backend(self, monkeypatch):
        monkeypatch.setattr("app.config.settings.checkpoint_backend", "sqlite")
        from app.api.dependencies import get_checkpoint_manager

        assert isinstance(get_checkpoint_manager(), SqliteCheckpointManager)

    def test_explicit_memory_backend(self, monkeypatch):
        monkeypatch.setattr("app.config.settings.checkpoint_backend", "memory")
        from app.api.dependencies import get_checkpoint_manager
        from app.orchestration import InMemoryCheckpointManager

        assert isinstance(get_checkpoint_manager(), InMemoryCheckpointManager)

    def test_auto_without_database_url_env_falls_to_sqlite(self, monkeypatch, tmp_path):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setattr("app.config.settings.checkpoint_backend", "auto")
        monkeypatch.setattr("app.config.settings.checkpoint_db_path", str(tmp_path / "ck.db"))
        from app.api.dependencies import get_checkpoint_manager

        assert isinstance(get_checkpoint_manager(), SqliteCheckpointManager)
