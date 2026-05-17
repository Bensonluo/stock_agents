"""Fundamental analysis tools. Extracted from app/agents/analysis_agent.py"""

from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.utils.logging import get_logger

logger = get_logger(__name__)


class AnalyzeFundamentalInput(BaseModel):
    financial_data: dict = Field(description="Financial data from fetch_stock_data")
    market_data: dict = Field(default={}, description="Market data for additional context")


@tool(args_schema=AnalyzeFundamentalInput)
def analyze_fundamental(financial_data: dict, market_data: dict = None) -> dict[str, Any]:
    """Evaluate financial health, profitability, and valuation."""
    results = {}
    market_data = market_data or {}

    for symbol, fin in financial_data.items():
        try:
            metrics = fin.get("metrics", {})
            mkt = market_data.get(symbol, {})
            profitability = _analyze_profitability(metrics)
            valuation = _analyze_valuation(metrics, mkt)
            health = _analyze_financial_health(metrics)
            p_score = profitability["score"]
            v_score = valuation["score"]
            h_score = health["score"]
            overall = p_score * 0.35 + v_score * 0.30 + h_score * 0.25 + 50 * 0.10
            results[symbol] = {
                "symbol": symbol,
                "profitability": profitability,
                "valuation": valuation,
                "financial_health": health,
                "overall_score": {"score": round(overall, 2), "rating": _score_to_rating(overall, 100)},
                "recommendation": _recommendation(overall),
            }
        except Exception as e:
            logger.error(f"Fundamental analysis failed for {symbol}: {e}")

    return results


def _analyze_profitability(metrics: dict) -> dict:
    score, details = 0, {}
    roe = metrics.get("roe")
    if roe:
        details["roe"] = float(roe)
        if roe >= 0.20: score += 40
        elif roe >= 0.15: score += 30
        elif roe >= 0.10: score += 20
        elif roe >= 0.05: score += 10
    roa = metrics.get("roa")
    if roa:
        details["roa"] = float(roa)
        if roa >= 0.10: score += 20
        elif roa >= 0.05: score += 15
        elif roa >= 0.02: score += 10
    pm = metrics.get("profit_margin")
    if pm:
        details["profit_margin"] = float(pm)
        if pm >= 0.20: score += 20
        elif pm >= 0.10: score += 15
        elif pm >= 0.05: score += 10
    om = metrics.get("operating_margin")
    if om:
        details["operating_margin"] = float(om)
        if om >= 0.15: score += 20
        elif om >= 0.10: score += 15
        elif om >= 0.05: score += 10
    return {"score": score, "rating": _score_to_rating(score, 100), "details": details}


def _analyze_valuation(metrics: dict, mkt: dict) -> dict:
    score, details = 0, {}
    pe = metrics.get("pe_ratio")
    if pe and 0 < pe <= 40:
        details["pe_ratio"] = float(pe)
        if pe <= 15: score += 30
        elif pe <= 25: score += 20
        elif pe <= 40: score += 10
    pb = metrics.get("pb_ratio")
    if pb and 0 < pb <= 3:
        details["pb_ratio"] = float(pb)
        if pb <= 1: score += 25
        elif pb <= 2: score += 20
        elif pb <= 3: score += 15
    ps = metrics.get("ps_ratio")
    if ps and 0 < ps <= 6:
        details["ps_ratio"] = float(ps)
        if ps <= 2: score += 25
        elif ps <= 4: score += 20
        elif ps <= 6: score += 15
    ev = metrics.get("ev_ebitda")
    if ev and 0 < ev <= 16:
        details["ev_ebitda"] = float(ev)
        if ev <= 8: score += 20
        elif ev <= 12: score += 15
        elif ev <= 16: score += 10
    return {"score": score, "rating": _score_to_rating(score, 100), "details": details}


def _analyze_financial_health(metrics: dict) -> dict:
    score, details = 0, {}
    de = metrics.get("debt_to_equity")
    if de is not None:
        details["debt_to_equity"] = float(de)
        if de <= 0.5: score += 40
        elif de <= 1: score += 30
        elif de <= 1.5: score += 20
        elif de <= 2: score += 10
    cr = metrics.get("current_ratio")
    if cr:
        details["current_ratio"] = float(cr)
        if cr >= 2: score += 30
        elif cr >= 1.5: score += 25
        elif cr >= 1: score += 15
    qr = metrics.get("quick_ratio")
    if qr:
        details["quick_ratio"] = float(qr)
        if qr >= 1.5: score += 30
        elif qr >= 1: score += 25
        elif qr >= 0.8: score += 15
    return {"score": score, "rating": _score_to_rating(score, 100), "details": details}


def _score_to_rating(score: float, max_score: float) -> str:
    pct = score / max_score if max_score > 0 else 0
    if pct >= 0.8: return "excellent"
    elif pct >= 0.6: return "good"
    elif pct >= 0.4: return "fair"
    elif pct >= 0.2: return "poor"
    else: return "very_poor"


def _recommendation(score: float) -> str:
    if score >= 75: return "strong_buy"
    elif score >= 60: return "buy"
    elif score >= 45: return "hold"
    elif score >= 30: return "sell"
    else: return "strong_sell"
