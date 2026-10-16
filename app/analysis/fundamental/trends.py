"""Fundamental trend annotations — iteration 190's multi-period history
consumed at the analysis seam. Pure annotation: nothing in scoring reads a
trend block, so attach/detach changes no score (pinned by test).

Two bases, one shape (``{basis, metrics}``):

    indicators_history (CN)      — Sina rows are YTD-cumulative, so the only
                                   honest comparison is same-period-prior-year;
                                   no anchor year → None, never a
                                   nearest-row stand-in dressed up as YoY.
    statements_quarterly (US/HK) — discrete quarters, QoQ is valid; the
                                   converted block is {dates, data} with the
                                   same visibility stamps the annual path has.
"""

from __future__ import annotations

import math
from typing import Any

_EPS = 1e-9

_YOY_METRICS = ("roe", "profit_margin", "gross_margin", "revenue_growth", "earnings_growth")
_QUARTER_ROWS = (("revenue", "Total Revenue"), ("net_income", "Net Income"))


def _direction(delta: float) -> str:
    if delta > _EPS:
        return "improving"
    if delta < -_EPS:
        return "deteriorating"
    return "flat"


def _number(value: Any) -> float | None:
    """Finite float or None — bools are not numbers here, NaN/None/strings
    are not trend points."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def yoy_metric_trends(indicators_history: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """CN history → latest row vs the same-period-prior-year row.

    Rows are ``{date: "YYYY-MM-DD", metrics: {...}}`` ascending (akshare
    sorts them; we sort defensively anyway). A metric participates only
    when BOTH the latest and the year-ago cell are real numbers.
    """
    if not indicators_history:
        return None
    by_date: dict[str, dict[str, Any]] = {}
    for row in indicators_history:
        date_key = row.get("date")
        if isinstance(date_key, str) and date_key:
            by_date[date_key] = row.get("metrics") or {}
    dates = sorted(by_date)
    if len(dates) < 2:
        return None
    latest = dates[-1]
    year, month_day = latest.split("-", 1)
    prior = f"{int(year) - 1}-{month_day}"
    if prior not in by_date:
        return None  # no same-period anchor → no honest YoY
    metrics_out: dict[str, Any] = {}
    for name in _YOY_METRICS:
        value = _number(by_date[latest].get(name))
        year_ago = _number(by_date[prior].get(name))
        if value is None or year_ago is None:
            continue
        delta = value - year_ago
        metrics_out[name] = {
            "value": value,
            "year_ago": year_ago,
            "delta": delta,
            "direction": _direction(delta),
        }
    if not metrics_out:
        return None
    return {"basis": "same_period_prior_year", "as_of": latest, "metrics": metrics_out}


def quarterly_statement_trends(
    statements_quarterly: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Quarterly income statement → per-row last-≤4-quarter QoQ view.

    Dates arrive in provider order (yfinance is newest-first); each row
    keeps its own series — a quarter missing for one line item drops out
    of that row's window only, never re-aligned across rows.
    """
    income = (statements_quarterly or {}).get("income_statement")
    if not isinstance(income, dict):
        return None
    dates = income.get("dates") or []
    rows = income.get("data") or {}
    if not dates:
        return None
    newest_first = sorted(range(len(dates)), key=lambda i: str(dates[i]), reverse=True)[:4]
    window = sorted(newest_first, key=lambda i: str(dates[i]))  # oldest → newest
    metrics_out: dict[str, Any] = {}
    for key, row_name in _QUARTER_ROWS:
        values = rows.get(row_name) or []
        pairs = [
            {"quarter": str(dates[i]), "value": number}
            for i in window
            if (number := _number(values[i] if i < len(values) else None)) is not None
        ]
        if len(pairs) < 2:
            continue  # one point is a level, not a trend
        delta = pairs[-1]["value"] - pairs[-2]["value"]
        metrics_out[key] = {
            "quarters": pairs,
            "latest_qoq_delta": delta,
            "direction": _direction(delta),
        }
    if not metrics_out:
        return None
    return {"basis": "quarter_over_quarter", "metrics": metrics_out}


def trend_annotation(financial_data_block: dict[str, Any] | None) -> dict[str, Any] | None:
    """One symbol's financial_data block → its trend annotation, if any.

    CN history wins when both are present (same-symbol precedence mirrors
    the data layer: a 6-digit symbol never carries statements_quarterly).
    """
    if not isinstance(financial_data_block, dict):
        return None
    trend = yoy_metric_trends(financial_data_block.get("indicators_history"))
    if trend is not None:
        return trend
    return quarterly_statement_trends(financial_data_block.get("statements_quarterly"))
