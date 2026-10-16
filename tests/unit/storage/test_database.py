"""Storage layer characterization pins — app/storage/database.py had zero
direct tests (only the in-memory eviction test touches the module, and it
mocks the DB away). These pins lock the SQLite contract the history API
and the analysis completion path both ride on:

    round-trips preserve the full result JSON verbatim (the trend /
    catalysts / consensus annotation blocks ride inside `result` — any
    storage-layer re-serialization or truncation would eat them),
    whitelist enforcement on update_record, result-preserving
    status-only update_status, pagination/filter/search ordering, and
    the thread_id UNIQUE constraint.

The Database is a __new__ singleton bound to the module-level DB_PATH, so
the fixture redirects DB_PATH to a tmp dir and resets the singleton —
production files are never touched, and the reset in teardown keeps the
singleton from leaking into other tests.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from app.storage.database import AnalysisRecord, Database


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.database.DB_PATH", tmp_path / "test_history.db")
    Database._instance = None  # fresh singleton against the tmp DB
    instance = Database()
    yield instance
    conn = getattr(instance._local, "conn", None)
    if conn is not None:
        conn.close()
    Database._instance = None


def _record(thread_id: str, **overrides) -> AnalysisRecord:
    """One completed CN run — the annotation blocks ride in `result`."""
    fields = {
        "thread_id": thread_id,
        "symbols": '["600519"]',
        "query": "贵州茅台基本面",
        "status": "completed",
        "result": json.dumps(
            {
                "report": {
                    "sections": {
                        "fundamental_analysis": {
                            "by_symbol": {
                                "600519": {
                                    "overall_score": {"score": 75},
                                    "trend": {"basis": "same_period_prior_year"},
                                }
                            }
                        }
                    }
                }
            },
            ensure_ascii=False,
        ),
        "execution_time": 12.5,
    }
    fields.update(overrides)
    return AnalysisRecord(**fields)


class TestCreateGet:
    def test_round_trip_preserves_every_field_verbatim(self, db) -> None:
        record_id = db.create_record(_record("t-1"))

        assert isinstance(record_id, int) and record_id > 0
        loaded = db.get_record("t-1")
        assert loaded is not None
        assert loaded.id == record_id
        assert loaded.thread_id == "t-1"
        assert loaded.symbols == '["600519"]'
        assert loaded.status == "completed"
        assert loaded.execution_time == 12.5
        # The result JSON comes back byte-for-byte — annotation blocks ride.
        assert json.loads(loaded.result)["report"]["sections"]["fundamental_analysis"]["by_symbol"][
            "600519"
        ]["trend"] == {"basis": "same_period_prior_year"}
        assert loaded.created_at and loaded.updated_at  # server-stamped

    def test_get_record_by_id_and_misses(self, db) -> None:
        record_id = db.create_record(_record("t-1"))

        assert db.get_record_by_id(record_id).thread_id == "t-1"
        assert db.get_record_by_id(99999) is None
        assert db.get_record("nope") is None

    def test_create_overwrites_client_timestamps_with_server_time(self, db) -> None:
        db.create_record(
            _record("t-1", created_at="1999-01-01T00:00:00", updated_at="1999-01-01T00:00:00")
        )

        loaded = db.get_record("t-1")
        assert loaded.created_at != "1999-01-01T00:00:00"

    def test_duplicate_thread_id_rejected_by_unique_constraint(self, db) -> None:
        db.create_record(_record("t-1"))

        with pytest.raises(sqlite3.IntegrityError):
            db.create_record(_record("t-1"))


class TestUpdates:
    def test_update_record_whitelist_rejects_unknown_columns(self, db) -> None:
        db.create_record(_record("t-1"))

        with pytest.raises(ValueError, match="Invalid columns"):
            db.update_record("t-1", result="x", evil_column="; DROP TABLE")

    def test_update_record_empty_kwargs_is_a_noop_false(self, db) -> None:
        db.create_record(_record("t-1"))

        assert db.update_record("t-1") is False

    def test_update_record_missing_thread_returns_false(self, db) -> None:
        assert db.update_record("ghost", status="failed") is False

    def test_update_status_without_result_keeps_the_existing_result(self, db) -> None:
        db.create_record(_record("t-1"))
        original = db.get_record("t-1").result

        assert db.update_status("t-1", "failed") is True
        loaded = db.get_record("t-1")
        assert loaded.status == "failed"
        assert loaded.result == original  # status-only update must not eat the report

    def test_update_status_with_result_overwrites(self, db) -> None:
        db.create_record(_record("t-1"))

        assert db.update_status("t-1", "completed", result='{"new": 1}', execution_time=9.0)
        loaded = db.get_record("t-1")
        assert loaded.result == '{"new": 1}'
        assert loaded.execution_time == 9.0

    def test_update_status_missing_thread_returns_false(self, db) -> None:
        assert db.update_status("ghost", "failed") is False


class TestListCountSearchDelete:
    def test_list_records_paginates_newest_first_and_filters_status(self, db) -> None:
        for i in range(5):
            db.create_record(_record(f"t-{i}", status="completed" if i % 2 else "failed"))

        page1 = db.list_records(limit=2, offset=0)
        page2 = db.list_records(limit=2, offset=2)
        assert [r.thread_id for r in page1] == ["t-4", "t-3"]  # newest first
        assert [r.thread_id for r in page2] == ["t-2", "t-1"]
        # i=0,2,4 → failed (3 records); i=1,3 → completed (2)
        assert len(db.list_records(limit=20, status="failed")) == 3
        assert len(db.list_records(limit=20, status="completed")) == 2

    def test_count_records_total_and_by_status(self, db) -> None:
        for i in range(3):
            db.create_record(_record(f"t-{i}", status="completed"))
        db.create_record(_record("t-9", status="failed"))

        assert db.count_records() == 4
        assert db.count_records(status="completed") == 3
        assert db.count_records(status="pending") == 0

    def test_search_matches_symbols_or_query_and_caps_limit(self, db) -> None:
        db.create_record(_record("t-1"))
        db.create_record(_record("t-2", query="茅台", symbols='["600519"]'))
        db.create_record(_record("t-3", query="特斯拉", symbols='["TSLA"]'))

        by_symbol = db.search_records("600519")
        assert [r.thread_id for r in by_symbol] == ["t-2", "t-1"]
        by_query = db.search_records("特斯拉")
        assert [r.thread_id for r in by_query] == ["t-3"]
        assert db.search_records("600519", limit=1) == [db.get_record("t-2")]
        assert db.search_records("nomatch") == []

    def test_delete_record_and_miss(self, db) -> None:
        db.create_record(_record("t-1"))

        assert db.delete_record("t-1") is True
        assert db.get_record("t-1") is None
        assert db.delete_record("t-1") is False


class TestSingleton:
    def test_database_is_a_new_singleton(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("app.storage.database.DB_PATH", tmp_path / "s1.db")
        Database._instance = None
        try:
            a = Database()
            b = Database()
            assert a is b
            assert Database._instance is a
        finally:
            conn = getattr(a._local, "conn", None)
            if conn is not None:
                conn.close()
            Database._instance = None

    def test_record_to_dict_shape(self, db) -> None:
        db.create_record(_record("t-1"))

        as_dict = db.get_record("t-1").to_dict()
        assert set(as_dict) == {
            "id",
            "thread_id",
            "symbols",
            "query",
            "status",
            "result",
            "created_at",
            "updated_at",
            "execution_time",
        }
