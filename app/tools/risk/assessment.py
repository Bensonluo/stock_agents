"""Risk assessment tools. Extracted from app/agents/risk_agent.py"""

from typing import Any

import numpy as np
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.utils.logging import get_logger

logger = get_logger(__name__)


class AssessRiskInput(BaseModel):
    market_data: dict = Field(description="Market data with historical prices")


@tool(args_schema=AssessRiskInput)
def assess_risk(market_data: dict) -> dict[str, Any]:
    """Calculate risk metrics (volatility, VaR, max drawdown, risk score)."""
    results = {}

    for symbol, data in market_data.items():
        try:
            hist = data.get("historical_data", {})
            closes = np.array(hist.get("close", []))
            if len(closes) < 20:
                results[symbol] = _minimal_risk(data)
                continue

            returns = np.diff(closes) / closes[:-1]
            volatility = float(np.std(returns))
            var_95 = float(np.percentile(returns, 5))
            var_99 = float(np.percentile(returns, 1))
            max_dd = _max_drawdown(closes)
            downside = _downside_risk(returns)
            risk_score = _calculate_score(volatility, max_dd, var_95, 1.0)
            risk_level = _score_to_level(risk_score)

            results[symbol] = {
                "symbol": symbol,
                "risk_score": risk_score,
                "risk_level": risk_level,
                "metrics": {
                    "volatility": volatility,
                    "volatility_annualized": float(volatility * np.sqrt(252)),
                    "var_95": var_95,
                    "var_99": var_99,
                    "max_drawdown": max_dd,
                    "downside_risk": downside,
                },
                "position_recommendation": {
                    "max_position_size": _position_size(risk_score),
                    "stop_loss_percentage": float(volatility * 2 * 100),
                },
                "warnings": _warnings(risk_level, volatility, max_dd),
            }
        except Exception as e:
            logger.error(f"Risk assessment failed for {symbol}: {e}")
            results[symbol] = _minimal_risk(data)

    return results


def _max_drawdown(prices: np.ndarray) -> float:
    cummax = np.maximum.accumulate(prices)
    drawdown = (cummax - prices) / cummax
    return float(np.max(drawdown))


def _downside_risk(returns: np.ndarray) -> float:
    neg = returns[returns < 0]
    return float(np.std(neg)) if len(neg) > 0 else 0.0


def _calculate_score(vol: float, dd: float, var: float, beta: float) -> float:
    score = 0
    if vol >= 0.03: score += 30
    elif vol >= 0.02: score += 20
    elif vol >= 0.015: score += 10
    if dd >= 0.3: score += 30
    elif dd >= 0.2: score += 20
    elif dd >= 0.1: score += 10
    if abs(var) >= 0.05: score += 20
    elif abs(var) >= 0.03: score += 15
    elif abs(var) >= 0.02: score += 10
    if beta >= 1.5: score += 20
    elif beta >= 1.2: score += 15
    return min(100, score)


def _score_to_level(score: float) -> str:
    if score >= 70: return "very_high"
    elif score >= 50: return "high"
    elif score >= 30: return "medium"
    elif score >= 15: return "low"
    else: return "very_low"


def _position_size(score: float) -> float:
    if score >= 70: return 2.0
    elif score >= 50: return 5.0
    elif score >= 30: return 10.0
    elif score >= 15: return 15.0
    else: return 20.0


def _warnings(level: str, vol: float, dd: float) -> list:
    warnings = []
    if level in ["high", "very_high"]:
        warnings.append("High risk stock. Consider smaller position size.")
    if vol > 0.03:
        warnings.append(f"High daily volatility ({vol*100:.1f}%).")
    if dd > 0.3:
        warnings.append(f"History of deep drawdowns ({dd*100:.1f}%).")
    return warnings


def _minimal_risk(data: dict) -> dict:
    return {
        "symbol": data.get("symbol", ""),
        "risk_score": 50,
        "risk_level": "medium",
        "metrics": {},
        "position_recommendation": {"max_position_size": 10.0},
        "warnings": ["Insufficient data for detailed risk assessment"],
    }
