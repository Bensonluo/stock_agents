"""Unit tests for the opt-in daily watchlist analysis run."""

from __future__ import annotations

import asyncio
import contextlib
import re
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import app.services.daily_run as daily_run_module
from app.analysis.ic import MIN_IC_SYMBOLS
from app.config import Settings, settings
from app.services.daily_run import (
    DAILY_RUN_QUERY,
    _next_run_at,
    _parse_symbols,
    _today_thread_id,
    run_daily_once,
)

_NOW = datetime(2026, 9, 29, 10, 0, 0)


def _orchestrator_mock(**kwargs):
    return SimpleNamespace(execute_workflow=AsyncMock(**kwargs))


def _db_mock(record=None):
    return SimpleNamespace(get_record=Mock(return_value=record))


# --- _next_run_at -----------------------------------------------------------


def test_next_run_at_before_time_returns_today() -> None:
    assert _next_run_at(_NOW, "16:00") == datetime(2026, 9, 29, 16, 0)


def test_next_run_at_after_time_returns_tomorrow() -> None:
    assert _next_run_at(datetime(2026, 9, 29, 17, 0), "16:00") == datetime(2026, 9, 30, 16, 0)


def test_next_run_at_exact_time_goes_to_tomorrow() -> None:
    # Pinned semantics: "already reached" includes equality — at exactly
    # HH:MM:00.000 the next occurrence is tomorrow, never a zero-delay rerun.
    assert _next_run_at(datetime(2026, 9, 29, 16, 0, 0), "16:00") == datetime(2026, 9, 30, 16, 0)


def test_next_run_at_strips_seconds_and_micros() -> None:
    nxt = _next_run_at(datetime(2026, 9, 29, 15, 30, 45, 123), "16:00")
    assert (nxt.second, nxt.microsecond) == (0, 0)


@pytest.mark.parametrize("bad", ["25:00", "16:61", "9am", "1600", "", "16"])
def test_next_run_at_invalid_format_raises(bad: str) -> None:
    with pytest.raises(ValueError):
        _next_run_at(_NOW, bad)


# --- _today_thread_id / _parse_symbols --------------------------------------


def test_today_thread_id_format() -> None:
    assert _today_thread_id(datetime(2026, 9, 29, 16, 3, 7)) == "daily-20260929"


def test_parse_symbols_strips_and_drops_empty() -> None:
    assert _parse_symbols("600000, AAPL , 00700,") == ["600000", "AAPL", "00700"]


def test_parse_symbols_single() -> None:
    assert _parse_symbols("AAPL") == ["AAPL"]


def test_parse_symbols_empty_stays_empty() -> None:
    assert _parse_symbols("") == []
    assert _parse_symbols(" , ") == []


def test_default_universe_feeds_the_measurement_chain() -> None:
    # The scheduler exists to feed the IC / calibration / adaptive-weight
    # machinery, and the IC views need >= MIN_IC_SYMBOLS scored symbols per
    # run to rank. A default watchlist thinner than that starves every view
    # except calibration on the feature's own defaults.
    default = Settings.model_fields["daily_run_symbols"].default
    symbols = _parse_symbols(default)
    assert len(symbols) >= MIN_IC_SYMBOLS
    assert len(set(symbols)) == len(symbols)


def test_default_universe_is_all_cn() -> None:
    # Production data-chain reality: server-side US symbols sit behind
    # Yahoo-429, and a dead leg drops out of the IC cross-section — the run
    # silently degrades back toward the minimum. Ship a CN-only default;
    # operators wanting US exposure opt in via DAILY_RUN_SYMBOLS.
    default = Settings.model_fields["daily_run_symbols"].default
    assert all(re.fullmatch(r"\d{6}", s) for s in _parse_symbols(default))


# --- run_daily_once ----------------------------------------------------------


@pytest.mark.asyncio
async def test_run_daily_once_executes_workflow(monkeypatch) -> None:
    monkeypatch.setattr(settings, "daily_run_symbols", "600000, AAPL")
    orchestrator = _orchestrator_mock(return_value={})
    monkeypatch.setattr(daily_run_module, "get_orchestrator", lambda: orchestrator)
    monkeypatch.setattr(daily_run_module, "get_database", lambda: _db_mock(record=None))

    result = await run_daily_once(datetime(2026, 9, 29, 16, 0, 30))

    assert result == "daily-20260929"
    orchestrator.execute_workflow.assert_awaited_once_with(
        query=DAILY_RUN_QUERY,
        symbols=["600000", "AAPL"],
        thread_id="daily-20260929",
    )


@pytest.mark.asyncio
async def test_run_daily_once_skips_when_record_exists(monkeypatch) -> None:
    monkeypatch.setattr(settings, "daily_run_symbols", "600000")
    orchestrator = _orchestrator_mock(return_value={})
    monkeypatch.setattr(daily_run_module, "get_orchestrator", lambda: orchestrator)
    # Any record for today's thread_id — regardless of status — means the day
    # is consumed (exactly-once guard, restart-safe).
    monkeypatch.setattr(
        daily_run_module, "get_database", lambda: _db_mock(record=SimpleNamespace(status="failed"))
    )

    assert await run_daily_once(datetime(2026, 9, 29, 16, 1)) is None
    orchestrator.execute_workflow.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_daily_once_skips_when_no_symbols(monkeypatch) -> None:
    monkeypatch.setattr(settings, "daily_run_symbols", " , ")
    orchestrator = _orchestrator_mock(return_value={})
    monkeypatch.setattr(daily_run_module, "get_orchestrator", lambda: orchestrator)
    db = _db_mock()
    monkeypatch.setattr(daily_run_module, "get_database", lambda: db)

    assert await run_daily_once(datetime(2026, 9, 29, 16, 1)) is None
    orchestrator.execute_workflow.assert_not_awaited()
    db.get_record.assert_not_called()


@pytest.mark.asyncio
async def test_run_daily_once_swallows_orchestrator_failure(monkeypatch) -> None:
    monkeypatch.setattr(settings, "daily_run_symbols", "600000")
    orchestrator = _orchestrator_mock(side_effect=RuntimeError("workflow exploded"))
    monkeypatch.setattr(daily_run_module, "get_orchestrator", lambda: orchestrator)
    monkeypatch.setattr(daily_run_module, "get_database", lambda: _db_mock(record=None))

    assert await run_daily_once(datetime(2026, 9, 29, 16, 1)) is None


@pytest.mark.asyncio
async def test_run_daily_once_swallows_db_failure(monkeypatch) -> None:
    monkeypatch.setattr(settings, "daily_run_symbols", "600000")

    def boom():
        raise RuntimeError("db locked")

    monkeypatch.setattr(daily_run_module, "get_database", boom)

    assert await run_daily_once(datetime(2026, 9, 29, 16, 1)) is None


# --- daily_run_loop wiring ----------------------------------------------------


@pytest.mark.asyncio
async def test_daily_run_loop_wires_schedule_to_execution(monkeypatch) -> None:
    calls: list[datetime] = []

    async def fake_once(now: datetime) -> str | None:
        calls.append(now)
        return None

    monkeypatch.setattr(daily_run_module, "run_daily_once", fake_once)
    monkeypatch.setattr(
        daily_run_module, "_next_run_at", lambda now, hhmm: now + timedelta(milliseconds=5)
    )

    task = asyncio.create_task(daily_run_module.daily_run_loop())
    try:
        for _ in range(200):
            if calls:
                break
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert calls, "loop never invoked run_daily_once"


@pytest.mark.asyncio
async def test_daily_run_loop_catches_up_when_trigger_already_passed(monkeypatch) -> None:
    """Restart after today's trigger: run immediately, not after the next sleep."""
    calls: list[datetime] = []

    async def fake_once(now: datetime) -> str | None:
        calls.append(now)
        return None

    monkeypatch.setattr(daily_run_module, "run_daily_once", fake_once)
    monkeypatch.setattr(
        daily_run_module, "_trigger_today", lambda now, hhmm: now - timedelta(hours=1)
    )
    # Next scheduled trigger far away — proves the call came from catch-up.
    monkeypatch.setattr(
        daily_run_module, "_next_run_at", lambda now, hhmm: now + timedelta(hours=12)
    )

    task = asyncio.create_task(daily_run_module.daily_run_loop())
    try:
        for _ in range(200):
            if calls:
                break
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert len(calls) == 1, "catch-up should fire exactly once, scheduler sleeps after"


@pytest.mark.asyncio
async def test_daily_run_loop_no_catchup_before_trigger(monkeypatch) -> None:
    """Restart before today's trigger: no immediate run, wait for the schedule."""
    calls: list[datetime] = []

    async def fake_once(now: datetime) -> str | None:
        calls.append(now)
        return None

    monkeypatch.setattr(daily_run_module, "run_daily_once", fake_once)
    monkeypatch.setattr(
        daily_run_module, "_trigger_today", lambda now, hhmm: now + timedelta(hours=1)
    )
    monkeypatch.setattr(
        daily_run_module, "_next_run_at", lambda now, hhmm: now + timedelta(hours=12)
    )

    task = asyncio.create_task(daily_run_module.daily_run_loop())
    try:
        await asyncio.sleep(0.05)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert calls == []


# --- lifespan wiring ----------------------------------------------------------


def _patched_loop_factory(monkeypatch, trace: list[str]):
    async def fake_loop() -> None:
        trace.append("started")
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(3600)
        trace.append("cancelled")

    monkeypatch.setattr(daily_run_module, "daily_run_loop", fake_loop)
    return fake_loop


def test_lifespan_default_off_starts_no_daily_loop(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr(settings, "daily_run_enabled", False)
    trace: list[str] = []
    _patched_loop_factory(monkeypatch, trace)

    with TestClient(app):
        assert trace == []


def test_lifespan_enabled_starts_and_cancels_daily_loop(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr(settings, "daily_run_enabled", True)
    monkeypatch.setattr(settings, "daily_run_time", "16:00")
    trace: list[str] = []
    _patched_loop_factory(monkeypatch, trace)

    with TestClient(app):
        assert trace == ["started"]

    assert trace == ["started", "cancelled"]


def test_lifespan_invalid_time_disables_daily_loop(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr(settings, "daily_run_enabled", True)
    monkeypatch.setattr(settings, "daily_run_time", "25:99")
    trace: list[str] = []
    _patched_loop_factory(monkeypatch, trace)

    with TestClient(app):
        assert trace == []
