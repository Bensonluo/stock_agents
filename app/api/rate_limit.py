"""In-process sliding-window rate limiting for expensive POST endpoints.

The product is publicly exposed (Live Demo) and every analyze POST spends
~162s of real multi-agent LLM work; every backtest POST burns CPU on the
bounded executor pool. This module fences those endpoints with a per-client
sliding window — stdlib only, in-process (mirrors bounded_store /
provider_health precedents; counters reset on restart, which is acceptable
for abuse protection).

Client key = the RIGHT-MOST X-Forwarded-For entry, else the socket peer.
Trust model: the production nginx proxy (deploy/nginx-full-config.conf) sets
`proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for`, which APPENDS
the client IP as seen by nginx as the last entry — so the right-most entry is
the address nginx actually served. Caveat: the API port is also exposed
directly by docker-compose; a client hitting :8001 directly can spoof XFF.
The public entry is through nginx, so right-most XFF is the right default.

GET endpoints (health/history/monitoring/progress) are intentionally
unlimited — cheap reads, and the demo stays unaffected.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from fastapi import HTTPException, Request

from app.config import settings

# bucket name -> (limit settings attr, window settings attr)
_BUCKET_SETTINGS = {
    "analysis": ("rate_limit_analysis_limit", "rate_limit_analysis_window_seconds"),
    "backtest": ("rate_limit_backtest_limit", "rate_limit_backtest_window_seconds"),
}


class SlidingWindowLimiter:
    """Per-key sliding window: at most ``limit`` hits per ``window_seconds``."""

    _MAX_TRACKED_KEYS = 10_000

    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, current: float) -> None:
        """Bound memory: a flood of distinct spoofed client keys must not
        grow the store unboundedly. Fully-expired keys go first, then the
        oldest-inserted keys (dict preserves insertion order)."""
        if len(self._hits) <= self._MAX_TRACKED_KEYS:
            return
        cutoff = current - self.window_seconds
        for key in [k for k, h in self._hits.items() if not h or h[-1] <= cutoff]:
            del self._hits[key]
        while len(self._hits) > self._MAX_TRACKED_KEYS:
            self._hits.pop(next(iter(self._hits)))

    def check(self, key: str, now: float | None = None) -> float | None:
        """Record a hit for ``key``; None if allowed, else retry-after seconds.

        Rejected requests are NOT recorded — a rejection never extends the
        window (the caller must wait for the oldest hit to expire).
        """
        current = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            cutoff = current - self.window_seconds
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(self.window_seconds - (current - hits[0]), 0.0)
            hits.append(current)
            self._prune(current)
            return None


# One limiter per bucket (in-process; resets on restart)
_LIMITERS: dict[str, SlidingWindowLimiter] = {}
_REGISTRY_LOCK = threading.Lock()


def reset_rate_limiter() -> None:
    """Clear all buckets (test seam; mirrors reset_provider_health)."""
    with _REGISTRY_LOCK:
        _LIMITERS.clear()


def _client_key(request: Request) -> str:
    """Right-most X-Forwarded-For entry, else the socket peer, else 'unknown'."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[-1].strip()
        if client_ip:
            return client_ip
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _get_limiter(bucket: str) -> SlidingWindowLimiter:
    limit_attr, window_attr = _BUCKET_SETTINGS[bucket]
    # Settings read at call time so instance-level overrides (tests, .env)
    # apply; a changed limit/window rebuilds the bucket fresh.
    limit = getattr(settings, limit_attr)
    window = float(getattr(settings, window_attr))
    with _REGISTRY_LOCK:
        limiter = _LIMITERS.get(bucket)
        if limiter is None or limiter.limit != limit or limiter.window_seconds != window:
            limiter = SlidingWindowLimiter(limit, window)
            _LIMITERS[bucket] = limiter
        return limiter


def rate_limit(bucket: str):
    """FastAPI dependency factory: 429 + Retry-After once the per-client
    sliding window for ``bucket`` is exhausted."""
    if bucket not in _BUCKET_SETTINGS:
        raise ValueError(f"unknown rate-limit bucket: {bucket}")

    def _dependency(request: Request) -> None:
        if not settings.rate_limit_enabled:
            return
        retry_after = _get_limiter(bucket).check(_client_key(request))
        if retry_after is not None:
            wait = int(retry_after) + 1  # ceil — never invite an early retry
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded — retry after {wait}s",
                headers={"Retry-After": str(wait)},
            )

    _dependency.rate_limit_bucket = bucket  # type: ignore[attr-defined]
    return _dependency
