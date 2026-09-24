"""Canonical fundamental scoring (V2 plan §5.1 — one implementation for pipeline and ReAct).

Threshold-based scoring over snapshot metrics with explicit insufficient_data
statuses; a missing metric never contributes a neutral score. Thresholds are
deliberately simple heuristics pending industry/percentile templates (Phase 4).
Component scores are normalized by the achievable maximum of the metrics
actually present — data availability must not read as poor quality (the
growth component always worked this way; the other three now match).
"""

from __future__ import annotations

from typing import Any

from app.utils.logging import get_logger

logger = get_logger(__name__)

# (metric key, max points, band direction, tiers). "at_least": points for
# value >= threshold, tiers descending. "at_most_positive": strictly positive
# values only (a non-positive PE is not "cheap"). "at_most_nonneg":
# non-negative values (zero debt is perfect; negative equity is distress).
_Spec = tuple[str, int, str, tuple[tuple[float, int], ...]]

_PROFITABILITY_SPECS: tuple[_Spec, ...] = (
    ("roe", 40, "at_least", ((0.20, 40), (0.15, 30), (0.10, 20), (0.05, 10))),
    ("roa", 20, "at_least", ((0.10, 20), (0.05, 15), (0.02, 10))),
    ("profit_margin", 20, "at_least", ((0.20, 20), (0.10, 15), (0.05, 10))),
    ("operating_margin", 20, "at_least", ((0.15, 20), (0.10, 15), (0.05, 10))),
)

_VALUATION_SPECS: tuple[_Spec, ...] = (
    ("pe_ratio", 30, "at_most_positive", ((15, 30), (25, 20), (40, 10))),
    ("pb_ratio", 25, "at_most_positive", ((1, 25), (2, 20), (3, 15))),
    ("ps_ratio", 25, "at_most_positive", ((2, 25), (4, 20), (6, 15))),
    ("ev_ebitda", 20, "at_most_positive", ((8, 20), (12, 15), (16, 10))),
)

_HEALTH_SPECS: tuple[_Spec, ...] = (
    ("debt_to_equity", 40, "at_most_nonneg", ((0.5, 40), (1, 30), (1.5, 20), (2, 10))),
    ("current_ratio", 30, "at_least", ((2, 30), (1.5, 25), (1, 15))),
    ("quick_ratio", 30, "at_least", ((1.5, 30), (1, 25), (0.8, 15))),
)


def analyze_fundamental_scoring(
    financial_data: dict, market_data: dict | None = None
) -> dict[str, Any]:
    """Score every symbol in ``financial_data`` ({symbol: {"metrics": ...}})."""
    results = {}
    market_data = market_data or {}

    for symbol, fin in financial_data.items():
        try:
            metrics = fin.get("metrics", {})
            mkt = market_data.get(symbol, {})
            profitability = _analyze_profitability(metrics)
            valuation = _analyze_valuation(metrics, mkt)
            health = _analyze_financial_health(metrics)
            growth = _analyze_growth(fin)
            overall = _calculate_overall_score(profitability, valuation, health, growth)
            results[symbol] = {
                "symbol": symbol,
                "profitability": profitability,
                "valuation": valuation,
                "financial_health": health,
                "growth": growth,
                "overall_score": overall,
                "recommendation": _recommendation(overall["score"]),
            }
        except Exception as e:
            logger.error(f"Fundamental analysis failed for {symbol}: {e}")

    return results


def _tier_points(value: float, direction: str, tiers: tuple[tuple[float, int], ...]) -> int:
    """Points for one metric under its band direction; 0 outside every band."""
    if direction == "at_most_positive" and value <= 0:
        return 0
    if direction == "at_most_nonneg" and value < 0:
        return 0
    if direction.startswith("at_most"):
        return next((points for upper, points in tiers if value <= upper), 0)
    return next((points for threshold, points in tiers if value >= threshold), 0)


def _score_component(metrics: dict, specs: tuple[_Spec, ...]) -> dict:
    """Score one component against the achievable maximum of present metrics.

    A symbol with only a PE ratio can earn at most 30 raw points; rating that
    30 against a hardcoded 100 called every PE-only name "poor" — missing
    data read as bad data. Normalizing by ``achievable`` keeps full-data
    scores bit-identical (every component's spec table sums to 100) and
    makes partial-data ratings reflect the quality of what is measurable.
    """
    raw = 0
    achievable = 0
    details: dict[str, float] = {}
    for key, max_points, direction, tiers in specs:
        value = metrics.get(key)
        if value is None:
            continue
        value = float(value)
        if value != value:  # NaN — never a scoreable observation
            continue
        details[key] = value
        achievable += max_points
        raw += _tier_points(value, direction, tiers)

    if not details:
        return {
            "score": 0,
            "rating": _score_to_rating(0, 100),
            "details": details,
            "status": "insufficient_data",
        }
    score = raw / achievable * 100 if achievable else 0.0
    return {
        "score": round(score, 2),
        "rating": _score_to_rating(score, 100),
        "details": details,
        "status": "available",
        "metrics_count": len(details),
    }


def _analyze_profitability(metrics: dict) -> dict:
    return _score_component(metrics, _PROFITABILITY_SPECS)


def _analyze_valuation(metrics: dict, mkt: dict | None = None) -> dict:
    return _score_component(metrics, _VALUATION_SPECS)


def _analyze_financial_health(metrics: dict) -> dict:
    return _score_component(metrics, _HEALTH_SPECS)


def _analyze_growth(financial_data: dict) -> dict:
    metrics = financial_data.get("metrics", {})
    growth_metrics = {
        "revenue_growth": metrics.get("revenue_growth"),
        "earnings_growth": metrics.get("earnings_growth"),
    }
    available = {key: value for key, value in growth_metrics.items() if value is not None}
    if not available:
        return {
            "score": None,
            "rating": "insufficient_data",
            "status": "insufficient_data",
            "details": {"note": "Growth analysis requires revenue or earnings growth data"},
        }

    def score_metric(value: float) -> int:
        if value >= 0.20:
            return 50
        if value >= 0.10:
            return 40
        if value >= 0.05:
            return 30
        if value >= 0:
            return 20
        if value >= -0.10:
            return 10
        return 0

    raw_score = sum(score_metric(float(value)) for value in available.values())
    score = raw_score / (50 * len(available)) * 100
    return {
        "score": round(score, 2),
        "rating": _score_to_rating(score, 100),
        "status": "available",
        "details": {key: float(value) for key, value in available.items()},
    }


def _calculate_overall_score(
    profitability: dict, valuation: dict, health: dict, growth: dict
) -> dict:
    components = {
        "profitability": (profitability, 0.35),
        "valuation": (valuation, 0.30),
        "health": (health, 0.25),
        "growth": (growth, 0.10),
    }
    available = {
        name: (component.get("score"), weight)
        for name, (component, weight) in components.items()
        if component.get("score") is not None and component.get("status") != "insufficient_data"
    }
    available_weight = sum(weight for _, weight in available.values())
    component_scores = {name: component.get("score") for name, (component, _) in components.items()}
    if available_weight == 0:
        return {
            "score": None,
            "components": component_scores,
            "rating": "insufficient_data",
            "status": "insufficient_data",
            "available_weight": 0.0,
        }

    overall = sum(score * weight for score, weight in available.values()) / available_weight
    return {
        "score": round(overall, 2),
        "components": component_scores,
        "rating": _score_to_rating(overall, 100),
        "status": "complete" if len(available) == len(components) else "partial",
        "available_weight": round(available_weight, 2),
    }


def _score_to_rating(score: float, max_score: float) -> str:
    pct = score / max_score if max_score > 0 else 0
    if pct >= 0.8:
        return "excellent"
    elif pct >= 0.6:
        return "good"
    elif pct >= 0.4:
        return "fair"
    elif pct >= 0.2:
        return "poor"
    else:
        return "very_poor"


def _recommendation(score: float | None) -> str:
    if score is None:
        return "insufficient_data"
    if score >= 75:
        return "strong_buy"
    elif score >= 60:
        return "buy"
    elif score >= 45:
        return "hold"
    elif score >= 30:
        return "sell"
    else:
        return "strong_sell"
