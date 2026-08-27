"""Fundamental quality engine (V2 plan §3.2.B, §5.1).

Financial trend, cash quality and red-flag checks computed from the snapshot
statements (``{dates, data}`` blocks produced by the data agent). Facts only —
scores and industry templates arrive in later phases; this engine states what
the numbers show and flags what contradicts them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.analysis.technical.engine import make_evidence
from app.domain.schemas import IssueSeverity

# Growth below this over the latest period is flagged as a revenue decline.
REVENUE_DECLINE_THRESHOLD = -0.10
# Gross-margin erosion (percentage points) vs the first observed period.
MARGIN_EROSION_PP = 5.0
# CFO below this fraction of net income questions earnings quality.
CFO_NI_FLAG = 0.8

# yfinance statement row names (with common aliases).
_REVENUE_ROWS = ("Total Revenue", "Revenues")
_GROSS_PROFIT_ROWS = ("Gross Profit",)
_NET_INCOME_ROWS = ("Net Income", "Net Income Common Stockholders")
_CFO_ROWS = ("Operating Cash Flow", "Total Cash From Operating Activities")
_CAPEX_ROWS = ("Capital Expenditure", "Capital Expenditures")
_EQUITY_ROWS = ("Stockholders Equity", "Total Stockholder Equity")


def financial_quality(
    financial_data: dict[str, Any],
    *,
    symbol: str,
    as_of: datetime | None = None,
    currency: str = "USD",
    source: str = "unknown",
) -> dict[str, Any]:
    """Trend / cash-quality / red-flag summary for one symbol (JSON-safe)."""
    cutoff = as_of or datetime.now(UTC)

    revenue = _series(financial_data.get("income_statement"), _REVENUE_ROWS)
    gross_profit = _series(financial_data.get("income_statement"), _GROSS_PROFIT_ROWS)
    net_income = _series(financial_data.get("income_statement"), _NET_INCOME_ROWS)
    cfo = _series(financial_data.get("cash_flow"), _CFO_ROWS)
    capex = _series(financial_data.get("cash_flow"), _CAPEX_ROWS)
    equity = _series(financial_data.get("balance_sheet"), _EQUITY_ROWS)

    result: dict[str, Any] = {
        "symbol": symbol,
        "as_of": cutoff.isoformat(),
        "currency": currency,
        "revenue_trend": None,
        "margin_trend": None,
        "cash_quality": None,
        "red_flags": [],
        "evidence": [],
    }

    if revenue is not None:
        result["revenue_trend"] = _trend(revenue)
        result["evidence"].extend(
            _trend_evidence(symbol, "revenue", revenue, currency, cutoff, source)
        )
    if revenue is not None and gross_profit is not None:
        result["margin_trend"] = _margin_trend(revenue, gross_profit)
    if cfo is not None:
        result["cash_quality"] = _cash_quality(cfo, net_income, capex)
        result["evidence"].extend(
            _cash_evidence(symbol, result["cash_quality"], currency, cutoff, source)
        )
    if equity is not None:
        result["equity_latest"] = equity[-1][1]

    result["red_flags"] = _red_flags(result)
    result["status"] = _status(result)

    critical = any(flag["severity"] == "critical" for flag in result["red_flags"])
    result["quality_note"] = (
        "critical red flag present — conclusions need manual review" if critical else None
    )
    result["evidence"] = [item.model_dump(mode="json") for item in result["evidence"]]
    return result


def compact_quality_view(result: dict[str, Any] | None) -> dict[str, Any]:
    """Report/LLM-facing summary of statement quality: verdict + red flags."""
    if not isinstance(result, dict) or result.get("status") in (None, "error", "unavailable"):
        return {"status": "unavailable"}
    if result.get("status") == "insufficient_data":
        return {"status": "insufficient_data"}

    revenue = result.get("revenue_trend") or {}
    cash = result.get("cash_quality") or {}
    return {
        "status": "available",
        "revenue_cagr": revenue.get("cagr"),
        "cfo_to_net_income": cash.get("cfo_to_net_income"),
        "red_flags": result.get("red_flags", []),
    }


def _series(statement: Any, row_names: tuple[str, ...]) -> list[tuple[str, float]] | None:
    """Extract a (period, value) series ordered oldest -> newest."""
    if not isinstance(statement, dict):
        return None
    data = statement.get("data") or {}
    dates = list(statement.get("dates") or [])
    for name in row_names:
        values = data.get(name)
        if isinstance(values, list) and dates and len(values) == len(dates):
            pairs = [
                (str(period), float(value))
                for period, value in zip(dates, values, strict=True)
                if value is not None
            ]
            if pairs:
                # yfinance statement columns run newest -> oldest.
                return _sorted_by_period(pairs)
    return None


def _sorted_by_period(pairs: list[tuple[str, float]]) -> list[tuple[str, float]]:
    return sorted(pairs, key=lambda item: item[0])


def _trend(series: list[tuple[str, float]]) -> dict[str, Any]:
    values = [value for _, value in series]
    periods = [period for period, _ in series]
    yoy = [
        {
            "period": periods[i],
            "growth": round(values[i] / values[i - 1] - 1, 4) if values[i - 1] > 0 else None,
        }
        for i in range(1, len(values))
    ]
    cagr = None
    if len(values) >= 2 and values[0] > 0 and values[-1] > 0 and len(values) > 1:
        years = max(len(values) - 1, 1)
        cagr = round((values[-1] / values[0]) ** (1 / years) - 1, 4)
    return {"periods": periods, "values": values, "yoy_growth": yoy, "cagr": cagr}


def _margin_trend(
    revenue: list[tuple[str, float]], gross_profit: list[tuple[str, float]]
) -> dict[str, Any] | None:
    revenue_by_period = dict(revenue)
    margins = [
        (period, round(profit / revenue_by_period[period], 4))
        for period, profit in gross_profit
        if revenue_by_period.get(period, 0) > 0
    ]
    if not margins:
        return None
    first, last = margins[0][1], margins[-1][1]
    return {
        "margins": [{"period": period, "gross_margin": value} for period, value in margins],
        "change_pp": round((last - first) * 100, 2),
    }


def _cash_quality(
    cfo: list[tuple[str, float]],
    net_income: list[tuple[str, float]] | None,
    capex: list[tuple[str, float]] | None,
) -> dict[str, Any]:
    latest_cfo = cfo[-1][1]
    quality: dict[str, Any] = {"cfo_latest": latest_cfo, "period": cfo[-1][0]}

    if net_income:
        latest_ni = net_income[-1][1]
        quality["net_income_latest"] = latest_ni
        quality["cfo_to_net_income"] = (
            round(latest_cfo / latest_ni, 4) if latest_ni not in (0, 0.0) else None
        )
    if capex:
        quality["fcf_latest"] = latest_cfo + capex[-1][1]
    return quality


def _red_flags(result: dict[str, Any]) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    cash = result.get("cash_quality") or {}

    cfo = cash.get("cfo_latest")
    ni = cash.get("net_income_latest")
    if cfo is not None and ni is not None and cfo < 0 < ni:
        flags.append(
            {
                "code": "negative_cfo_positive_ni",
                "severity": IssueSeverity.CRITICAL.value,
                "detail": "Reported profit without operating cash flow.",
            }
        )

    revenue = result.get("revenue_trend") or {}
    yoy = revenue.get("yoy_growth") or []
    if yoy and yoy[-1]["growth"] is not None and yoy[-1]["growth"] < REVENUE_DECLINE_THRESHOLD:
        flags.append(
            {
                "code": "revenue_decline",
                "severity": IssueSeverity.WARNING.value,
                "detail": f"Latest revenue growth {yoy[-1]['growth'] * 100:.1f}%.",
            }
        )

    margin = result.get("margin_trend")
    if margin and margin["change_pp"] < -MARGIN_EROSION_PP:
        flags.append(
            {
                "code": "margin_erosion",
                "severity": IssueSeverity.WARNING.value,
                "detail": f"Gross margin changed {margin['change_pp']:+.1f}pp over the window.",
            }
        )

    equity = result.get("equity_latest")
    if equity is not None and equity < 0:
        flags.append(
            {
                "code": "negative_equity",
                "severity": IssueSeverity.CRITICAL.value,
                "detail": "Stockholders equity is negative.",
            }
        )

    return flags


def _status(result: dict[str, Any]) -> str:
    if result["revenue_trend"] is None and result["cash_quality"] is None:
        return "insufficient_data"
    if result["revenue_trend"] is None or result["cash_quality"] is None:
        return "partial"
    return "available"


def _trend_evidence(
    symbol: str,
    name: str,
    series: list[tuple[str, float]],
    currency: str,
    cutoff: datetime,
    source: str,
) -> list:
    cagr = (_trend(series) or {}).get("cagr")
    if cagr is None:
        return []
    return [
        make_evidence(
            symbol=symbol,
            name=f"{name}_cagr",
            value=cagr,
            unit="ratio",
            cutoff=cutoff,
            source=source,
            formula="(value_last / value_first) ** (1 / periods) - 1",
            params={"periods": len(series) - 1, "period_unit": "statement"},
            domain="fundamental",
        )
    ]


def _cash_evidence(
    symbol: str, cash: dict[str, Any], currency: str, cutoff: datetime, source: str
) -> list:
    evidence = []
    if cash.get("cfo_latest") is not None:
        evidence.append(
            make_evidence(
                symbol=symbol,
                name="cfo_latest",
                value=cash["cfo_latest"],
                unit=currency,
                cutoff=cutoff,
                source=source,
                formula="Operating Cash Flow (latest statement period)",
                params={"period": cash.get("period")},
                domain="fundamental",
            )
        )
    if cash.get("fcf_latest") is not None:
        evidence.append(
            make_evidence(
                symbol=symbol,
                name="fcf_latest",
                value=cash["fcf_latest"],
                unit=currency,
                cutoff=cutoff,
                source=source,
                formula="Operating Cash Flow + Capital Expenditure",
                params={"period": cash.get("period")},
                domain="fundamental",
            )
        )
    return evidence


__all__ = ["compact_quality_view", "financial_quality"]
