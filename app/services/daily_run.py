"""Opt-in daily watchlist analysis run (scheduler feeding the IC evidence base).

Turns the IC / calibration / adaptive-weight machinery from hand-fed to
self-fed: one analysis workflow per calendar day over the configured
watchlist, persisted to ``analysis_history`` by the orchestrator exactly like
a manual run, so IC replay consumes it with zero special-casing.

Semantics (deliberate boundaries):

- **Exactly-once per calendar day.** The run uses thread_id
  ``daily-YYYYMMDD``; if ``analysis_history`` already holds a record for it
  (any status — a failed run also consumes the day), the run is skipped.
  This makes the guard restart-safe: a crash after the record was written
  cannot double-run on restart.
- **Missed trigger catches up.** If the server was down at the trigger time,
  a same-day restart attempts the run immediately at loop startup (the
  exactly-once guard makes the attempt safe); the next scheduled trigger is
  tomorrow as usual.
- **Holidays run anyway.** No trading calendar; stale data is handled
  honestly downstream (freshness annotation + confidence cap), not by
  skipping the day.
- **Concurrency-safe with manual runs.** Distinct thread_ids mean distinct
  LangGraph configs; no shared mutable state.
- **Invalid ``DAILY_RUN_TIME``** raises ``ValueError`` on the first schedule
  computation; ``app.main`` pre-checks this at startup and abandons the
  scheduler with an error log instead of running a zombie task.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from app.api.dependencies import get_orchestrator
from app.config import settings
from app.storage.database import get_database
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Lands in the DB record and the generated report — kept stable so history
# queries can filter scheduled runs by query text.
DAILY_RUN_QUERY = "每日自选股例行分析"


def _parse_hhmm(hhmm: str) -> tuple[int, int]:
    """Parse ``HH:MM`` into (hour, minute); raise ValueError on anything else."""
    parts = hhmm.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"expected HH:MM, got {hhmm!r}")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"time out of range: {hhmm!r}")
    return hour, minute


def _trigger_today(now: datetime, hhmm: str) -> datetime:
    """Today's HH:MM trigger moment (seconds/micros zeroed)."""
    hour, minute = _parse_hhmm(hhmm)
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _next_run_at(now: datetime, hhmm: str) -> datetime:
    """Next trigger occurrence: today's HH:MM if not yet reached, else tomorrow.

    "Already reached" includes equality — at exactly HH:MM:00.000 the next
    occurrence is tomorrow (prevents a zero-delay double-run on wake).
    """
    candidate = _trigger_today(now, hhmm)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def _today_thread_id(now: datetime) -> str:
    """Deterministic per-day thread id (DB- and log-safe date string)."""
    return f"daily-{now.strftime('%Y%m%d')}"


def _parse_symbols(raw: str) -> list[str]:
    """Comma-separated config string -> stripped, empties dropped."""
    return [part.strip() for part in raw.split(",") if part.strip()]


async def run_daily_once(now: datetime) -> str | None:
    """Execute today's scheduled run at most once; never raises.

    Returns the thread_id on success, None when skipped (no symbols, already
    ran today) or on any failure (logged, swallowed — a dead scheduler must
    not take the app down, and the exactly-once record decides retries).
    """
    thread_id = _today_thread_id(now)
    try:
        symbols = _parse_symbols(settings.daily_run_symbols)
        if not symbols:
            logger.info("[DailyRun] no symbols configured (DAILY_RUN_SYMBOLS empty); skipping")
            return None

        if get_database().get_record(thread_id) is not None:
            logger.info(f"[DailyRun] {thread_id} already recorded; skipping (exactly-once per day)")
            return None

        logger.info(f"[DailyRun] starting: thread_id={thread_id}, symbols={symbols}")
        await get_orchestrator().execute_workflow(
            query=DAILY_RUN_QUERY,
            symbols=symbols,
            thread_id=thread_id,
        )
        return thread_id
    except Exception as exc:
        logger.error(f"[DailyRun] failed (thread_id={thread_id}): {exc}")
        return None


async def daily_run_loop() -> None:
    """Sleep-until-trigger loop; one ``run_daily_once`` per wake-up.

    Before the first sleep, a restart catch-up runs: if today's trigger
    moment already passed while the app was down, ``run_daily_once`` fires
    immediately (the exactly-once DB guard makes it a no-op when today
    already ran). Without this the first sleep after a post-trigger restart
    would jump straight to tomorrow and lose the day.

    The loop body never raises: ``run_daily_once`` swallows everything, and
    ``asyncio.sleep`` only raises ``CancelledError`` (shutdown). An invalid
    ``DAILY_RUN_TIME`` surfaces here as ValueError on the first schedule
    computation — treated as a config error and pre-checked by the lifespan
    caller, which abandons the scheduler instead.
    """
    logger.info(
        f"[DailyRun] scheduler started: time={settings.daily_run_time}, "
        f"symbols={settings.daily_run_symbols}"
    )
    now = datetime.now()
    if now >= _trigger_today(now, settings.daily_run_time):
        logger.info("[DailyRun] trigger already passed today; attempting catch-up run")
        await run_daily_once(now)
    while True:
        now = datetime.now()
        delay = (_next_run_at(now, settings.daily_run_time) - now).total_seconds()
        logger.info(f"[DailyRun] next run in {delay / 3600:.2f}h")
        await asyncio.sleep(delay)
        await run_daily_once(datetime.now())
