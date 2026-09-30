"""Global admission control for analysis workflows.

The per-client rate limiter (``rate_limit.py``) bounds what ONE client can
request; nothing bounded how many full analysis workflows may run at once.
Each analyze POST is ~162s of multi-agent LLM work — a handful of concurrent
clients could stack unbounded pipelines and trip the LLM provider's own
limits (or burn the token budget) even when every client is individually
within its rate budget.

In-process counter, same trust model as the rate limiter: single uvicorn
worker, state resets on restart. Admission happens at REQUEST time so a
full server can 503 immediately instead of silently queuing; the slot is
released by whichever coroutine finishes the work — the inline await for
``/analyze/sync``, the background task for the fire-and-forget routes.
"""

import threading
from collections.abc import Callable
from contextlib import contextmanager

from fastapi import HTTPException

from app.config import settings

_LOCK = threading.Lock()
_IN_FLIGHT = 0


def in_flight() -> int:
    """Current number of admitted (running or queued) analyses."""
    with _LOCK:
        return _IN_FLIGHT


def reset_analysis_capacity() -> None:
    """Test seam: zero the counter (fixtures reset before and after)."""
    global _IN_FLIGHT
    with _LOCK:
        _IN_FLIGHT = 0


def reserve_analysis_slot() -> Callable[[], None]:
    """Admit one analysis run; returns the release callable.

    Raises HTTPException 503 (with Retry-After) when the server is at
    ``settings.max_concurrent_analyses``; a cap of 0 disables the guard.
    """
    global _IN_FLIGHT
    with _LOCK:
        cap = settings.max_concurrent_analyses
        if cap and _IN_FLIGHT >= cap:
            raise HTTPException(
                status_code=503,
                detail="Analysis capacity in use — retry shortly",
                headers={"Retry-After": "60"},
            )
        _IN_FLIGHT += 1

    def _release() -> None:
        global _IN_FLIGHT
        with _LOCK:
            _IN_FLIGHT = max(0, _IN_FLIGHT - 1)

    return _release


@contextmanager
def analysis_slot():
    """Inline wrapper: hold one slot for the duration of the ``with`` block."""
    release = reserve_analysis_slot()
    try:
        yield
    finally:
        release()
