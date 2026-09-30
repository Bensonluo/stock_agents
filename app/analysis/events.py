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


# Catalyst horizon buckets, ascending. The wire bucket is the literal key
# (``"1w"``/``"1m"``/``"3m"``/``"later"``) the frontend groups on.
CATALYST_BUCKETS = ("1w", "1m", "3m", "later")


def bucket_for(days_until: int) -> str:
    """Catalyst horizon bucket for a day distance.

    ``"1w"`` ≤7 days, ``"1m"`` ≤31, ``"3m"`` ≤92, everything farther out
    ``"later"``. Pure thresholds — negative distances are the caller's
    problem (``build_catalysts_view`` drops them before bucketing).
    """
    if days_until <= 7:
        return "1w"
    if days_until <= 31:
        return "1m"
    if days_until <= 92:
        return "3m"
    return "later"


def build_catalysts_view(
    symbol: str,
    event_calendar: Any = None,
    earnings_surprise: Any = None,
    *,
    today: date | str | None = None,
) -> dict[str, Any]:
    """Upcoming catalyst events + recent EPS surprise history for one symbol.

    Reads the data layer's ``event_calendar`` (``{"upcoming": [...],
    "as_of": iso}``) and ``earnings_surprise`` (``{"last_4": [...]}``)
    blocks. ``days_until`` is computed against ``today`` — injectable so
    tests and replays are deterministic; it defaults to ``date.today()``.

    Never raises and is JSON-safe by construction: malformed shapes
    contribute nothing, ``date`` objects are re-emitted as ISO strings,
    and ``detail`` rides only when it is a non-empty dict. Events with
    ``days_until < 0`` are dropped (the past is history, not a catalyst);
    the rest are sorted by date ascending (stable, so same-day events
    keep their input order). ``earnings_surprise`` is the last-4 row list
    verbatim (shallow-copied — the view never aliases upstream state), or
    ``[]`` when nothing has reported. ``symbol`` is accepted for
    symmetry/traceability; the report nests the view under the symbol
    key, so it is not duplicated on the wire.
    """
    del symbol  # traceability only — see docstring
    as_of = _parse_day(today) if today is not None else date.today()
    if as_of is None:  # unparsable injection → fall back to real today
        as_of = date.today()

    events: list[dict[str, Any]] = []
    upcoming: Any = None
    if isinstance(event_calendar, dict):
        upcoming = event_calendar.get("upcoming")
    elif isinstance(event_calendar, list):  # defensive: bare list delivery
        upcoming = event_calendar
    if isinstance(upcoming, list):
        for record in upcoming:
            if not isinstance(record, dict):
                continue
            day = _parse_day(record.get("date"))
            if day is None:
                continue
            days_until = (day - as_of).days
            if days_until < 0:
                continue
            event: dict[str, Any] = {
                "date": day.isoformat(),
                "days_until": days_until,
                "bucket": bucket_for(days_until),
                "type": str(record.get("type") or "other"),
                "title": str(record.get("title") or ""),
            }
            detail = record.get("detail")
            if isinstance(detail, dict) and detail:
                event["detail"] = detail
            events.append(event)
    events.sort(key=lambda event: event["date"])

    surprise: list[dict[str, Any]] = []
    last_4: Any = None
    if isinstance(earnings_surprise, dict):
        last_4 = earnings_surprise.get("last_4")
    elif isinstance(earnings_surprise, list):  # defensive: bare list delivery
        last_4 = earnings_surprise
    if isinstance(last_4, list):
        surprise = [dict(row) for row in last_4 if isinstance(row, dict)]

    return {"events": events, "earnings_surprise": surprise}
