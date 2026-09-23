"""Bull vs Bear cross-examination (V2 plan §3.2.H, §6).

Deterministic extraction of the strongest arguments on both sides from an
analysis packet. Every point carries an ``evidence_ref`` pointing at the
block it came from — arguments may not cite numbers that are not in the
packet. LLM narration can wrap this later; the selection itself must stay
reproducible.
"""

from __future__ import annotations

from typing import Any

# Max arguments kept per side.
MAX_POINTS_PER_SIDE = 3

TECHNICAL_REF = "technical_analysis.signals+weekly_sma"
FUNDAMENTAL_REF = "fundamental_analysis"
QUALITY_REF = "fundamental_analysis.quality"
VALUATION_REF = "fundamental_analysis.valuation_scenarios"
SENTIMENT_REF = "sentiment_analysis"
RISK_REF = "risk_assessment.metrics"


def bull_bear_debate(symbol: str, packet: dict[str, Any]) -> dict[str, Any]:
    """Extract bull/bear arguments for one symbol from its analysis blocks."""
    technical = packet.get("technical_analysis") or {}
    fundamental = packet.get("fundamental_analysis") or {}
    sentiment_flat = packet.get("sentiment_analysis") or {}
    risk = packet.get("risk_assessment") or {}

    bull: list[dict[str, Any]] = []
    bear: list[dict[str, Any]] = []

    _technical_arguments(technical, bull, bear)
    _fundamental_arguments(fundamental, bull, bear)
    _sentiment_arguments(sentiment_flat, bull, bear)
    _risk_arguments(risk, bear)

    bull.sort(key=lambda point: point["strength"], reverse=True)
    bear.sort(key=lambda point: point["strength"], reverse=True)

    top_bull = bull[0] if bull else None
    top_bear = bear[0] if bear else None

    return {
        "symbol": symbol,
        "bull_points": bull[:MAX_POINTS_PER_SIDE],
        "bear_points": bear[:MAX_POINTS_PER_SIDE],
        "thesis": top_bull["claim"] if top_bull else None,
        "strongest_counter": top_bear["claim"] if top_bear else None,
        "invalidation": _invalidation(bear),
    }


def _invalidation(bear: list[dict[str, Any]]) -> str | None:
    """The fact that would kill the bull thesis: first critical bear point."""
    for point in bear:
        if point.get("severity") == "critical":
            return point["claim"]
    return bear[0]["claim"] if bear else None


def _technical_arguments(technical: dict, bull: list, bear: list) -> None:
    signals = technical.get("signals") or {}
    trend = str(signals.get("trend", "neutral"))
    score = (technical.get("sentiment") or {}).get("score", 0) or 0

    if trend in ("bullish", "strong_bullish"):
        bull.append(
            {
                "claim": f"Daily trend is {trend} (technical sentiment {score:+.0f}).",
                "evidence_ref": TECHNICAL_REF,
                "strength": 60 if trend == "strong_bullish" else 40,
            }
        )
    elif trend in ("bearish", "strong_bearish"):
        bear.append(
            {
                "claim": f"Daily trend is {trend} (technical sentiment {score:+.0f}).",
                "evidence_ref": TECHNICAL_REF,
                "strength": 60 if trend == "strong_bearish" else 40,
            }
        )

    weekly = technical.get("weekly_sma") or {}
    alignment = (weekly.get("alignment") or {}).get("state")
    weeks = (weekly.get("alignment") or {}).get("weeks_in_state") or 0
    if alignment == "bullish":
        bull.append(
            {
                "claim": f"Weekly SMA alignment is bullish for {weeks} weeks.",
                "evidence_ref": TECHNICAL_REF,
                "strength": min(90, 50 + weeks),
            }
        )
    elif alignment == "bearish":
        bear.append(
            {
                "claim": f"Weekly SMA alignment is bearish for {weeks} weeks.",
                "evidence_ref": TECHNICAL_REF,
                "strength": min(90, 50 + weeks),
            }
        )

    for _pair, cross in (weekly.get("crosses") or {}).items():
        if cross.get("status") == "observed" and (cross.get("weeks_since") or 99) <= 8:
            if cross.get("direction") == "golden":
                bull.append(
                    {
                        "claim": f"Recent golden cross ({cross['weeks_since']} weeks ago, return since {cross.get('return_since_pct', 0):+.1f}%).",
                        "evidence_ref": TECHNICAL_REF,
                        "strength": 55,
                    }
                )
            else:
                bear.append(
                    {
                        "claim": f"Recent death cross ({cross['weeks_since']} weeks ago).",
                        "evidence_ref": TECHNICAL_REF,
                        "strength": 55,
                    }
                )


def _fundamental_arguments(fundamental: dict, bull: list, bear: list) -> None:
    quality = fundamental.get("quality") or {}
    for flag in quality.get("red_flags") or []:
        bear.append(
            {
                "claim": f"Red flag: {flag.get('detail') or flag.get('code')}",
                "evidence_ref": QUALITY_REF,
                "strength": 85 if flag.get("severity") == "critical" else 45,
                "severity": flag.get("severity"),
            }
        )

    revenue = quality.get("revenue_trend") or {}
    cagr = revenue.get("cagr") if isinstance(revenue, dict) else None
    if isinstance(cagr, int | float):
        if cagr >= 0.10:
            bull.append(
                {
                    "claim": f"Revenue CAGR {cagr:+.1%} across the statement window.",
                    "evidence_ref": QUALITY_REF,
                    "strength": min(80, 40 + int(cagr * 100)),
                }
            )
        elif cagr < 0:
            bear.append(
                {
                    "claim": f"Revenue contracting at {cagr:+.1%} CAGR.",
                    "evidence_ref": QUALITY_REF,
                    "strength": 50,
                }
            )

    scenarios = (fundamental.get("valuation_scenarios") or {}).get("scenarios") or {}
    bull_upside = _upside_from(scenarios, "bull")
    bear_upside = _upside_from(scenarios, "bear")
    if bull_upside is not None and bull_upside >= 10:
        bull.append(
            {
                "claim": f"Bull-case valuation implies {bull_upside:+.1f}% upside (stated assumptions).",
                "evidence_ref": VALUATION_REF,
                "strength": min(75, 30 + int(bull_upside)),
            }
        )
    if bear_upside is not None and bear_upside <= -20:
        bear.append(
            {
                "claim": f"Bear-case valuation implies {bear_upside:+.1f}% downside.",
                "evidence_ref": VALUATION_REF,
                "strength": min(75, 30 + int(abs(bear_upside))),
            }
        )


def _upside_from(scenarios: dict[str, Any], side: str) -> float | None:
    values = []
    for _method, blocks in scenarios.items():
        upside = (blocks or {}).get("upside_pct")
        if isinstance(upside, int | float):
            values.append(upside)
    return min(values) if side == "bear" and values else (max(values) if values else None)


def _sentiment_arguments(sentiment: dict, bull: list, bear: list) -> None:
    score = sentiment.get("score", 0) or 0
    if score >= 30:
        bull.append(
            {
                "claim": f"News sentiment is strongly positive ({score:+.0f}).",
                "evidence_ref": SENTIMENT_REF,
                "strength": min(50, 20 + int(score / 2)),
            }
        )
    elif score <= -30:
        bear.append(
            {
                "claim": f"News sentiment is strongly negative ({score:+.0f}).",
                "evidence_ref": SENTIMENT_REF,
                "strength": min(50, 20 + int(abs(score) / 2)),
            }
        )


def _risk_arguments(risk: dict, bear: list) -> None:
    metrics = risk.get("metrics") or {}
    stress = (risk.get("stress_scenarios") or {}).get("scenarios") or {}
    shock = stress.get("market_-20pct")
    if isinstance(shock, int | float) and shock <= -0.30:
        bear.append(
            {
                "claim": f"A -20% market shock implies roughly {shock:+.0%} here (beta {metrics.get('beta')}).",
                "evidence_ref": RISK_REF,
                "strength": min(70, 40 + int(abs(shock) * 100)),
            }
        )
