"""Provider health counters for the stock data chain.

The chain's provider outcomes (ok / fail / fallback) were previously
visible only through log archaeology — the 2026-09 East Money domain block
and the multi-day Yahoo 429 stretch were each discovered by reading logs
after the fact. This module is a pure in-process side channel: the fetcher
and data agent record each seam's outcome, the monitoring API exposes the
snapshot. Mirrors the AgentMonitor precedent (module-level state, no
persistence — counters reset on restart).

Recording must never change a data path's behavior: unknown outcomes and
empty provider names are silently ignored, and ``record_provider_outcome``
cannot raise for any caller-supplied value. All reads/writes run under one
``threading.Lock`` because the fetcher's sync seams execute inside
asyncio.to_thread workers — concurrent records from many threads are the
production shape, not an edge case.
"""

import threading
from copy import deepcopy
from datetime import datetime
from typing import Any

# One bounded line: a stack dump must not leak into the snapshot payload.
_MAX_DETAIL_CHARS = 200

_VALID_OUTCOMES = frozenset({"ok", "fail", "fallback"})

_lock = threading.Lock()
_counters: dict[str, dict[str, Any]] = {}


def _new_provider_state() -> dict[str, Any]:
    return {
        "total_calls": 0,
        "ok": 0,
        "fail": 0,
        "fallback": 0,
        "last_ok_at": None,
        "last_error": None,
        "last_error_at": None,
    }


def _clean_detail(detail: Any) -> str | None:
    """Detail as one line capped at 200 chars; None when there is nothing to say."""
    if not detail:
        return None
    one_line = " ".join(str(detail).splitlines()).strip()
    return one_line[:_MAX_DETAIL_CHARS] or None


def record_provider_outcome(provider: str, outcome: str, detail: str | None = None) -> None:
    """Record one provider attempt's outcome.

    Outcomes:
        ok       — the provider served the data itself.
        fail     — the provider errored or returned nothing usable.
        fallback — the primary died but a fallback caught the request: data
                   was served AND the primary's error happened, so both
                   recency fields move (last_ok_at and last_error*).

    A ``fail``/``fallback`` without a detail keeps the previous error
    summary — the count is still the count, the diagnosis is not erased.
    Unknown outcomes or empty provider names are ignored entirely.
    """
    if outcome not in _VALID_OUTCOMES or not provider:
        return
    cleaned = _clean_detail(detail)
    now = datetime.now().isoformat()
    with _lock:
        state = _counters.setdefault(provider, _new_provider_state())
        state["total_calls"] += 1
        state[outcome] += 1
        if outcome in ("ok", "fallback"):
            state["last_ok_at"] = now
        if outcome in ("fail", "fallback"):
            state["last_error_at"] = now
            if cleaned is not None:
                state["last_error"] = cleaned


def provider_health_snapshot() -> dict[str, Any]:
    """Deep copy of every provider's counters plus a generated_at stamp.

    The copy is load-bearing: callers may mutate the snapshot (API layers,
    tests) without poisoning the live counters.
    """
    with _lock:
        providers = deepcopy(_counters)
    return {"providers": providers, "generated_at": datetime.now().isoformat()}


def reset_provider_health() -> None:
    """Clear every provider's counters (tests; explicit ops resets)."""
    with _lock:
        _counters.clear()
