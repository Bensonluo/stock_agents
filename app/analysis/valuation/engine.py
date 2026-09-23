"""Valuation engine (V2 plan §3.2.C, §5.1).

Scenario-based valuation producing a value RANGE, never a single target
price. Two transparent methods are used with the data actually available
from the snapshot:

1. ``earnings_multiple`` — forward EPS scenarios × a multiple band anchored
   to the stock's own current P/E (not industry-generic thresholds).
2. ``sales_multiple`` — current price × forward revenue growth × a band of
   the stock's own sales multiple; used when earnings are absent or
   negative (loss-making growth template).

Every scenario's assumptions (growth shift, multiple factor) are stated in
the output so reviewers can challenge them; a 3×3 sensitivity table shows
how the base value moves.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.analysis.technical.engine import make_evidence
from app.domain.schemas import MetricEvidence

# Multiple band applied to the stock's own current multiple, per scenario.
# Anchoring to the stock's own multiple keeps the scenarios relative; the
# sensitivity table exposes how sensitive conclusions are to this band.
MULTIPLE_FACTORS = {"bear": 0.75, "base": 1.0, "bull": 1.25}
GROWTH_SHIFTS = {"bear": -0.05, "base": 0.0, "bull": 0.05}
# Growth scenarios are clipped so a single noisy growth print cannot produce
# absurd forward values.
GROWTH_CLIP = (-0.5, 0.5)

SCENARIOS = ("bear", "base", "bull")


def scenario_valuation(
    *,
    symbol: str,
    current_price: float | None,
    trailing_eps: float | None,
    ps_ratio: float | None,
    earnings_growth: float | None = None,
    revenue_growth: float | None = None,
    as_of: datetime | None = None,
    currency: str = "USD",
    source: str = "unknown",
) -> dict[str, Any]:
    """Bear/Base/Bull implied value range with sensitivity; JSON-safe."""
    cutoff = as_of or datetime.now(UTC)
    methods: dict[str, Any] = {}
    evidence: list[MetricEvidence] = []

    earnings = _earnings_method(
        symbol=symbol,
        current_price=current_price,
        trailing_eps=trailing_eps,
        earnings_growth=earnings_growth,
        cutoff=cutoff,
        currency=currency,
        source=source,
    )
    if earnings:
        methods["earnings_multiple"] = earnings
        evidence.extend(earnings.pop("_evidence"))

    sales = _sales_method(
        symbol=symbol,
        current_price=current_price,
        ps_ratio=ps_ratio,
        revenue_growth=revenue_growth,
        cutoff=cutoff,
        currency=currency,
        source=source,
    )
    if sales:
        methods["sales_multiple"] = sales
        evidence.extend(sales.pop("_evidence"))

    if not methods:
        return {
            "symbol": symbol,
            "status": "insufficient_data",
            "reason": "valuation needs a positive EPS or a positive price with a sales multiple",
            "as_of": cutoff.isoformat(),
            "methods": {},
            "evidence": [],
        }

    return {
        "symbol": symbol,
        "status": "available",
        "as_of": cutoff.isoformat(),
        "currency": currency,
        "methods": methods,
        "evidence": [item.model_dump(mode="json") for item in evidence],
    }


def sensitivity_table(base_value: float, growth: float) -> dict[str, Any]:
    """3×3 grid of implied values over the multiple band × growth shifts."""
    growth_scenarios = {name: _clip_growth(growth + shift) for name, shift in GROWTH_SHIFTS.items()}
    grid = {}
    for growth_name, growth_value in growth_scenarios.items():
        row = {}
        for factor_name, factor in MULTIPLE_FACTORS.items():
            row[factor_name] = round(base_value * (1 + growth_value) * factor, 4)
        grid[growth_name] = row
    return {
        "rows": "growth scenario (growth shift applied to base value)",
        "columns": f"multiple factor {MULTIPLE_FACTORS}",
        "values": grid,
    }


def _earnings_method(
    *,
    symbol: str,
    current_price: float | None,
    trailing_eps: float | None,
    earnings_growth: float | None,
    cutoff: datetime,
    currency: str,
    source: str,
) -> dict[str, Any] | None:
    """Forward-EPS × own-multiple band; None when earnings evidence is missing."""
    if not trailing_eps or trailing_eps <= 0 or not current_price or current_price <= 0:
        return None

    current_pe = current_price / trailing_eps
    growth = earnings_growth if earnings_growth is not None else 0.0

    implied: dict[str, Any] = {}
    for scenario in SCENARIOS:
        eps_forward = trailing_eps * (1 + _clip_growth(growth + GROWTH_SHIFTS[scenario]))
        value = eps_forward * current_pe * MULTIPLE_FACTORS[scenario]
        implied[scenario] = {
            "value": round(value, 4),
            "upside_pct": round((value / current_price - 1) * 100, 4),
            "assumptions": {
                "eps_forward": round(eps_forward, 4),
                "pe_multiple": round(current_pe * MULTIPLE_FACTORS[scenario], 4),
                "growth_used": _clip_growth(growth + GROWTH_SHIFTS[scenario]),
            },
        }

    method = {
        "status": "available",
        "current_pe": round(current_pe, 4),
        "scenarios": implied,
        "sensitivity": sensitivity_table(current_price, growth),
        "_evidence": _evidence_for(
            symbol=symbol,
            prefix="valuation_earnings",
            values={name: item["value"] for name, item in implied.items()},
            formula="eps * (1 + g) * current_pe * factor",
            params={"current_pe": round(current_pe, 4), "factors": MULTIPLE_FACTORS},
            unit=currency,
            cutoff=cutoff,
            source=source,
        ),
    }
    return method


def _sales_method(
    *,
    symbol: str,
    current_price: float | None,
    ps_ratio: float | None,
    revenue_growth: float | None,
    cutoff: datetime,
    currency: str,
    source: str,
) -> dict[str, Any] | None:
    """Price × forward revenue growth × own-multiple band for the sales method."""
    if not current_price or current_price <= 0 or not ps_ratio or ps_ratio <= 0:
        return None

    growth = revenue_growth if revenue_growth is not None else 0.0

    implied: dict[str, Any] = {}
    for scenario in SCENARIOS:
        value = (
            current_price
            * (1 + _clip_growth(growth + GROWTH_SHIFTS[scenario]))
            * MULTIPLE_FACTORS[scenario]
        )
        implied[scenario] = {
            "value": round(value, 4),
            "upside_pct": round((value / current_price - 1) * 100, 4),
            "assumptions": {
                "revenue_growth_used": _clip_growth(growth + GROWTH_SHIFTS[scenario]),
                "ps_factor": MULTIPLE_FACTORS[scenario],
            },
        }

    return {
        "status": "available",
        "current_ps": round(ps_ratio, 4),
        "scenarios": implied,
        "sensitivity": sensitivity_table(current_price, growth),
        "_evidence": _evidence_for(
            symbol=symbol,
            prefix="valuation_sales",
            values={name: item["value"] for name, item in implied.items()},
            formula="price * (1 + g_revenue) * factor",
            params={"current_ps": round(ps_ratio, 4), "factors": MULTIPLE_FACTORS},
            unit=currency,
            cutoff=cutoff,
            source=source,
        ),
    }


def compact_valuation_view(result: dict[str, Any] | None) -> dict[str, Any]:
    """Report/LLM-facing summary of a scenario valuation: range + upside only."""
    if not isinstance(result, dict) or result.get("status") in (None, "error", "unavailable"):
        return {"status": "unavailable"}
    if result.get("status") == "insufficient_data":
        return {"status": "insufficient_data", "reason": result.get("reason")}

    scenarios_out: dict[str, Any] = {}
    for method_name, method in (result.get("methods") or {}).items():
        for scenario, item in (method.get("scenarios") or {}).items():
            scenarios_out.setdefault(scenario, {})[method_name] = {
                "value": item.get("value"),
                "upside_pct": item.get("upside_pct"),
            }
    return {"status": "available", "as_of": result.get("as_of"), "scenarios": scenarios_out}


def _clip_growth(growth: float) -> float:
    return round(max(GROWTH_CLIP[0], min(GROWTH_CLIP[1], growth)), 4)


def _evidence_for(
    *,
    symbol: str,
    prefix: str,
    values: dict[str, float],
    formula: str,
    params: dict[str, Any],
    unit: str,
    cutoff: datetime,
    source: str,
) -> list[MetricEvidence]:
    return [
        make_evidence(
            symbol=symbol,
            name=f"{prefix}_{scenario}",
            value=value,
            unit=unit,
            cutoff=cutoff,
            source=source,
            formula=formula,
            params={**params, "scenario": scenario},
            domain="valuation",
        )
        for scenario, value in values.items()
    ]
