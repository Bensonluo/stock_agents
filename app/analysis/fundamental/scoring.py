"""Canonical fundamental scoring (V2 plan §5.1 — one implementation for pipeline and ReAct).

Threshold-based scoring over snapshot metrics with explicit insufficient_data
statuses; a missing metric never contributes a neutral score. Thresholds are
deliberately simple heuristics pending industry/percentile templates (Phase 4).
"""

from __future__ import annotations

from typing import Any

from app.utils.logging import get_logger

logger = get_logger(__name__)


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


def _analyze_profitability(metrics: dict) -> dict:
    score, details = 0, {}
    roe = metrics.get("roe")
    if roe is not None:
        details["roe"] = float(roe)
        if roe >= 0.20:
            score += 40
        elif roe >= 0.15:
            score += 30
        elif roe >= 0.10:
            score += 20
        elif roe >= 0.05:
            score += 10
    roa = metrics.get("roa")
    if roa is not None:
        details["roa"] = float(roa)
        if roa >= 0.10:
            score += 20
        elif roa >= 0.05:
            score += 15
        elif roa >= 0.02:
            score += 10
    pm = metrics.get("profit_margin")
    if pm is not None:
        details["profit_margin"] = float(pm)
        if pm >= 0.20:
            score += 20
        elif pm >= 0.10:
            score += 15
        elif pm >= 0.05:
            score += 10
    om = metrics.get("operating_margin")
    if om is not None:
        details["operating_margin"] = float(om)
        if om >= 0.15:
            score += 20
        elif om >= 0.10:
            score += 15
        elif om >= 0.05:
            score += 10
    return {
        "score": score,
        "rating": _score_to_rating(score, 100),
        "details": details,
        "status": "available" if details else "insufficient_data",
    }


def _analyze_valuation(metrics: dict, mkt: dict) -> dict:
    score, details = 0, {}
    pe = metrics.get("pe_ratio")
    if pe is not None:
        details["pe_ratio"] = float(pe)
        if 0 < pe <= 15:
            score += 30
        elif 0 < pe <= 25:
            score += 20
        elif 0 < pe <= 40:
            score += 10
    pb = metrics.get("pb_ratio")
    if pb is not None:
        details["pb_ratio"] = float(pb)
        if 0 < pb <= 1:
            score += 25
        elif 0 < pb <= 2:
            score += 20
        elif 0 < pb <= 3:
            score += 15
    ps = metrics.get("ps_ratio")
    if ps is not None:
        details["ps_ratio"] = float(ps)
        if 0 < ps <= 2:
            score += 25
        elif 0 < ps <= 4:
            score += 20
        elif 0 < ps <= 6:
            score += 15
    ev = metrics.get("ev_ebitda")
    if ev is not None:
        details["ev_ebitda"] = float(ev)
        if 0 < ev <= 8:
            score += 20
        elif 0 < ev <= 12:
            score += 15
        elif 0 < ev <= 16:
            score += 10
    return {
        "score": score,
        "rating": _score_to_rating(score, 100),
        "details": details,
        "status": "available" if details else "insufficient_data",
    }


def _analyze_financial_health(metrics: dict) -> dict:
    score, details = 0, {}
    de = metrics.get("debt_to_equity")
    if de is not None:
        details["debt_to_equity"] = float(de)
        if 0 <= de <= 0.5:
            score += 40
        elif de <= 1:
            score += 30
        elif de <= 1.5:
            score += 20
        elif de <= 2:
            score += 10
    cr = metrics.get("current_ratio")
    if cr is not None:
        details["current_ratio"] = float(cr)
        if cr >= 2:
            score += 30
        elif cr >= 1.5:
            score += 25
        elif cr >= 1:
            score += 15
    qr = metrics.get("quick_ratio")
    if qr is not None:
        details["quick_ratio"] = float(qr)
        if qr >= 1.5:
            score += 30
        elif qr >= 1:
            score += 25
        elif qr >= 0.8:
            score += 15
    return {
        "score": score,
        "rating": _score_to_rating(score, 100),
        "details": details,
        "status": "available" if details else "insufficient_data",
    }


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
