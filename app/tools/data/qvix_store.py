"""Local QVIX persistence (stdlib sqlite3, sync, fail-soft).

QVIX arrives through a third-party host (optbbs.com) with no SLA — every
successful fetch upserts the daily series here so an outage can serve the
last known closes from disk. Mirrors ``app/storage/database.py``'s
``data/`` directory convention. All operations fail soft: a broken or
unwritable DB file logs one warning and returns empty/0/None — it must
never crash the data pipeline.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.utils.logging import get_logger

logger = get_logger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "qvix.db"


class QvixStore:
    """Tiny append-only daily-close store; one connection per operation."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path is not None else DB_PATH

    def _connect(self) -> sqlite3.Connection | None:
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path))
            conn.execute(
                "CREATE TABLE IF NOT EXISTS qvix_daily ("
                "date TEXT PRIMARY KEY, close REAL NOT NULL)"
            )
            return conn
        except Exception as e:  # broken path / unreadable file — degrade, never raise
            logger.warning(f"[qvix_store] cannot open {self._db_path}: {e}")
            return None

    def upsert_many(self, rows: list[tuple[str, float]]) -> None:
        """INSERT OR REPLACE daily closes; last write per date wins."""
        if not rows:
            return
        conn = self._connect()
        if conn is None:
            return
        try:
            conn.executemany("INSERT OR REPLACE INTO qvix_daily(date, close) VALUES (?, ?)", rows)
            conn.commit()
        except Exception as e:
            logger.warning(f"[qvix_store] upsert failed ({len(rows)} rows): {e}")
        finally:
            conn.close()

    def trailing_closes(self, days: int) -> list[float]:
        """Most recent ``days`` closes, newest first."""
        conn = self._connect()
        if conn is None:
            return []
        try:
            rows = conn.execute(
                "SELECT close FROM qvix_daily ORDER BY date DESC LIMIT ?", (days,)
            ).fetchall()
            return [float(r[0]) for r in rows]
        except Exception as e:
            logger.warning(f"[qvix_store] trailing_closes failed: {e}")
            return []
        finally:
            conn.close()

    def last_row(self) -> tuple[str, float] | None:
        """Newest (date, close) pair; None when the store is empty/unreadable."""
        conn = self._connect()
        if conn is None:
            return None
        try:
            row = conn.execute(
                "SELECT date, close FROM qvix_daily ORDER BY date DESC LIMIT 1"
            ).fetchone()
            return (str(row[0]), float(row[1])) if row else None
        except Exception as e:
            logger.warning(f"[qvix_store] last_row failed: {e}")
            return None
        finally:
            conn.close()

    def row_count(self) -> int:
        conn = self._connect()
        if conn is None:
            return 0
        try:
            return int(conn.execute("SELECT COUNT(*) FROM qvix_daily").fetchone()[0])
        except Exception as e:
            logger.warning(f"[qvix_store] row_count failed: {e}")
            return 0
        finally:
            conn.close()


_store: QvixStore | None = None


def get_qvix_store() -> QvixStore:
    """Process-wide default store (tests inject their own QvixStore instance)."""
    global _store
    if _store is None:
        _store = QvixStore()
    return _store
