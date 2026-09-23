"""Shared bounded-store eviction for long-lived in-memory caches.

Both the workflow status store and the API-layer workflow result cache are
process-lifetime dicts that would otherwise grow without bound. The policy
here: evict the oldest terminal entry first; only when every entry is still
live does the oldest entry get evicted regardless of status.
"""

from collections.abc import Callable, Container
from typing import Any

DEFAULT_TERMINAL_STATUSES = ("completed", "failed")


def evict_oldest_terminal(
    store: dict,
    max_size: int,
    *,
    terminal_statuses: Container[str] = DEFAULT_TERMINAL_STATUSES,
    timestamp_of: Callable[[Any], Any] | None = None,
    on_evict: Callable[[str], None] | None = None,
) -> str | None:
    """Evict one entry when the store is at capacity.

    Args:
        store: The dict cache to trim (mutated in place).
        max_size: Capacity; nothing happens below it.
        terminal_statuses: Statuses eligible for first-chance eviction.
        timestamp_of: Sort key over entry values; defaults to the entry's
            "updated_at" field (missing -> empty string sorts oldest).
        on_evict: Optional cleanup callback receiving the evicted key
            (e.g. dropping a companion log store).

    Returns:
        The evicted key, or None when the store was under capacity.
    """
    if len(store) < max_size:
        return None

    if timestamp_of is None:

        def timestamp_of(entry: Any) -> Any:  # noqa: F811 - local default
            return entry.get("updated_at", "") if isinstance(entry, dict) else ""

    terminal = [
        key
        for key, entry in store.items()
        if isinstance(entry, dict) and entry.get("status") in terminal_statuses
    ]
    pool = terminal or list(store)
    victim = min(pool, key=lambda key: timestamp_of(store[key]))
    del store[victim]
    if on_evict is not None:
        on_evict(victim)
    return victim
