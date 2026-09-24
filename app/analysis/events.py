"""Event calendar analysis.

Earnings dates are the recurring scheduled-uncertainty window a research
report must disclose: a position opened three days before the print is a
different trade than the same position opened three weeks before it. The
helpers here are pure calendar math over the record lists the data layer
emits (``[{"date": iso, ...}, ...]``) — nothing fetches, nothing scores.
"""

from __future__ import annotations

from datetime import date
from typing import Any


def _parse_day(value: Any) -> date | None:
    """Accept ISO strings and datetimes; None when nothing usable."""
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def next_earnings_window(
    records: list[dict[str, Any]] | None, *, as_of: date | str | None = None
) -> dict[str, Any] | None:
    """The next scheduled earnings date on or after ``as_of``.

    Returns ``{"next_earnings_date": iso, "days_until": int}`` for the
    earliest future date, or None when the calendar holds no upcoming date
    (empty feed, all quarters already reported, or unparsable dates) — an
    absent event is honestly absent, never "today" by default.
    """
    if not isinstance(records, list) or not records:
        return None
    today = _parse_day(as_of) if as_of is not None else date.today()
    if today is None:
        return None

    upcoming = [
        day
        for record in records
        if isinstance(record, dict)
        and (day := _parse_day(record.get("date"))) is not None
        and day >= today
    ]
    if not upcoming:
        return None
    next_day = min(upcoming)
    return {
        "next_earnings_date": next_day.isoformat(),
        "days_until": (next_day - today).days,
    }
