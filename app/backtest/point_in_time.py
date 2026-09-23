"""Point-in-time financial data (V2 plan §7.1).

A financial statement for period ending 2024-12-31 is NOT visible on
2024-12-31 — only after it is filed. Backtests that join statements by
period-end date peek into the future. This module makes visibility explicit:
every period gets a ``visible_from`` date (period end + a reporting lag), and
lookups at a historical ``as_of`` only ever return periods already visible.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

# Conservative default: annual reports ~90 days after period end, quarterly
# ~45; a single 60-day lag is a defensible middle ground until per-filing
# dates (SEC EDGAR / CNEXchange) are wired in Phase 4.
DEFAULT_REPORTING_LAG_DAYS = 60


def visible_from(period_end: str | date, lag_days: int = DEFAULT_REPORTING_LAG_DAYS) -> date:
    """The first date a statement for ``period_end`` could have been used."""
    end = _as_date(period_end)
    if lag_days < 0:
        raise ValueError("lag_days must be non-negative")
    return end + timedelta(days=lag_days)


def stamp_visibility(
    statement_block: dict[str, Any], lag_days: int = DEFAULT_REPORTING_LAG_DAYS
) -> dict[str, Any]:
    """Return the statement block with a ``visible_from`` list added.

    The block shape is the data-agent's: ``{"dates": [...], "data": {...}}``.
    ``visible_from`` aligns index-wise with ``dates``.
    """
    dates = statement_block.get("dates") or []
    return {
        **statement_block,
        "visible_from": [visible_from(d, lag_days).isoformat() for d in dates],
    }


def visible_values_at(
    statement_block: dict[str, Any],
    as_of: str | date,
    row: str,
    *,
    lag_days: int = DEFAULT_REPORTING_LAG_DAYS,
) -> list[tuple[str, float]]:
    """(period, value) pairs for ``row`` that were visible at ``as_of``.

    Values that are not numbers or are missing are skipped. Using this instead
    of reading ``data[row][-1]`` is what keeps a backtest free of look-ahead.
    """
    cutoff = _as_date(as_of)
    dates = statement_block.get("dates") or []
    values = (statement_block.get("data") or {}).get(row) or []

    visible: list[tuple[str, float]] = []
    for period_end, value in zip(dates, values, strict=False):
        if visible_from(period_end, lag_days) > cutoff:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        visible.append((str(period_end), number))

    # Statements arrive newest-first (yfinance style); oldest-to-newest is the
    # order "latest visible" logic depends on.
    return sorted(visible, key=lambda item: _as_date(item[0]))


def latest_visible_value(
    statement_block: dict[str, Any],
    as_of: str | date,
    row: str,
    *,
    lag_days: int = DEFAULT_REPORTING_LAG_DAYS,
) -> float | None:
    """Most recent visible value for ``row``; None when nothing was visible."""
    visible = visible_values_at(statement_block, as_of, row, lag_days=lag_days)
    return visible[-1][1] if visible else None


def _as_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])
