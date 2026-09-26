"""Risk Committee (V2 plan §3.3, §6).

Gate that reviews audited research and returns approve / limit / veto / watch
per symbol. The committee CANNOT create a buy direction — low risk alone
never justifies a position; it can only restrict or permit what the evidence
already supports.
"""

from __future__ import annotations

from typing import Any

# The committee's high-risk / crash-shock position cap. Stated in the limit
# verdict's conditions AND carried as position_cap_pct — the ReAct gate
# applies `min(position_size, position_cap)`, so a limit verdict without the
# cap field never actually bounded the published position.
LIMIT_POSITION_CAP_PCT = 5.0


def committee_review(
    symbol: str,
    *,
    risk: dict[str, Any] | None,
    quality: dict[str, Any] | None,
    audit_verdict: str,
) -> dict[str, Any]:
    """Decide the risk gate for one symbol.

    Returns a verdict, optional position cap and mandatory conditions.
    """
    conditions: list[str] = []

    if audit_verdict == "blocked":
        return _decision(
            "veto",
            ["Evidence auditor blocked this packet: stale data or critical conflicts."],
        )

    quality = quality or {}
    critical_flags = [
        flag for flag in quality.get("red_flags") or [] if flag.get("severity") == "critical"
    ]
    if critical_flags:
        return _decision(
            "veto",
            [
                f"Critical fundamental red flag: {flag.get('detail') or flag.get('code')}"
                for flag in critical_flags
            ],
        )

    risk = risk or {}
    risk_level = str(risk.get("risk_level", "insufficient_data"))
    stress = (risk.get("stress_scenarios") or {}).get("scenarios") or {}
    shock_20 = stress.get("market_-20pct")

    if risk_level == "insufficient_data" or not risk:
        return _decision(
            "watch",
            ["Risk metrics insufficient — observations only, no position conclusion."],
        )

    position = risk.get("position_recommendation") or {}
    suggested = position.get("max_position_size")

    if risk_level == "very_high":
        return _decision("veto", ["Risk level is very_high."])

    if risk_level == "high" or (isinstance(shock_20, int | float) and shock_20 <= -0.30):
        conditions.append("Position capped at 5% of portfolio.")
        conditions.append("A stop-loss is mandatory.")
        if isinstance(suggested, int | float):
            conditions.append(f"Engine suggested {suggested}% — capped by committee.")
        return _decision("limit", conditions, position_cap_pct=LIMIT_POSITION_CAP_PCT)

    if risk_level == "medium":
        conditions.append("Size within suggested limit; monitor volatility percentile.")
        return _decision("approve", conditions, position_cap_pct=suggested)

    conditions.append(
        "Low measured risk does NOT itself justify a position; direction must come from valuation/momentum evidence."
    )
    return _decision("approve", conditions, position_cap_pct=suggested)


def _decision(
    verdict: str, conditions: list[str], position_cap_pct: float | None = None
) -> dict[str, Any]:
    return {
        "verdict": verdict,
        "conditions": conditions,
        "position_cap_pct": position_cap_pct,
    }
