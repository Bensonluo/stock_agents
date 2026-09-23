"""Risk assessment tools. Extracted from app/agents/risk_agent.py"""

from typing import Any

import numpy as np
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.analysis.risk import (
    aligned_returns,
    calculate_beta,
    cvar_historical,
    downside_deviation,
    max_drawdown,
    relative_risk_metrics,
    sortino_ratio,
    stress_scenarios,
    to_returns,
    volatility_percentile,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Backwards-compatible aliases for callers importing the historical private names.
_aligned_returns = aligned_returns
_calculate_beta = calculate_beta
_max_drawdown = max_drawdown
_downside_risk = downside_deviation


def _calculate_beta_from_histories(
    stock_history: dict, benchmark_history: dict | None
) -> float | None:
    if not benchmark_history:
        return None
    stock, benchmark = aligned_returns(stock_history, benchmark_history)
    return calculate_beta(stock, benchmark)


class AssessRiskInput(BaseModel):
    market_data: dict = Field(description="Market data with historical prices")


@tool(args_schema=AssessRiskInput)
def assess_risk(market_data: dict) -> dict[str, Any]:
    """Calculate risk metrics (volatility, VaR/CVaR, beta, drawdown, stress)."""
    results = {}

    for symbol, data in market_data.items():
        try:
            results[symbol] = _assess_symbol(symbol, data)
        except Exception as e:
            logger.error(f"Risk assessment failed for {symbol}: {e}")
            results[symbol] = _minimal_risk(data, symbol)

    return results


def _assess_symbol(symbol: str, data: dict) -> dict[str, Any]:
    hist = data.get("historical_data", {})
    closes = np.array(hist.get("close", []))
    if len(closes) < 20:
        return _minimal_risk(data, symbol)

    returns = to_returns(closes)
    volatility = float(np.std(returns))
    var_95 = float(np.percentile(returns, 5))
    var_99 = float(np.percentile(returns, 1))
    cvar_95 = cvar_historical(returns, level=0.95)
    max_dd = max_drawdown(closes)
    downside = downside_deviation(returns)
    sortino = sortino_ratio(returns)
    vol_percentile = volatility_percentile(returns)

    benchmark_history = _get_benchmark_history(data)
    stock_returns, benchmark_returns = _paired_returns(hist, benchmark_history)
    beta = calculate_beta(stock_returns, benchmark_returns)
    relative = (
        relative_risk_metrics(stock_returns, benchmark_returns)
        if benchmark_returns is not None
        else {}
    )
    stress = stress_scenarios(beta)

    risk_score = _calculate_score(volatility, max_dd, var_95, beta)
    risk_level = _score_to_level(risk_score)
    beta_status = "available" if beta is not None else "insufficient_data"

    return {
        "symbol": symbol,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "risk_score_status": "complete" if beta is not None else "partial",
        "metrics": {
            "volatility": volatility,
            "volatility_annualized": float(volatility * np.sqrt(252)),
            "var_95": var_95,
            "var_99": var_99,
            "cvar_95": cvar_95,
            "max_drawdown": max_dd,
            "downside_risk": downside,
            "sortino": sortino,
            "volatility_percentile_20d": vol_percentile,
            "beta": relative.get("beta", beta),
            "beta_status": beta_status,
            "alpha_annualized": relative.get("alpha_annualized"),
            "r_squared": relative.get("r_squared"),
            "correlation": relative.get("correlation"),
        },
        "stress_scenarios": stress,
        "position_recommendation": {
            "max_position_size": _position_size(risk_score) if beta is not None else None,
            "stop_loss_percentage": float(volatility * 2 * 100),
            "status": "available" if beta is not None else "insufficient_data",
        },
        "warnings": _warnings(risk_level, volatility, max_dd, beta_status),
    }


def _paired_returns(
    stock_history: dict, benchmark_history: dict | None
) -> tuple[np.ndarray, np.ndarray | None]:
    """Aligned stock/benchmark returns; benchmark side is None without history."""
    if not benchmark_history:
        return np.array([]), None
    stock, benchmark = aligned_returns(stock_history, benchmark_history)
    if len(stock) == 0:
        return np.array([]), None
    return stock, benchmark


def _get_benchmark_history(data: dict) -> dict | None:
    """Return benchmark history only when it was explicitly supplied."""
    direct = data.get("benchmark_historical_data")
    if isinstance(direct, dict):
        return direct

    benchmark = data.get("benchmark_data")
    if not isinstance(benchmark, dict):
        return None
    nested = benchmark.get("historical_data")
    return nested if isinstance(nested, dict) else benchmark


def _calculate_score(
    vol: float | None, dd: float | None, var: float | None, beta: float | None
) -> float | None:
    """Risk score 0-100 (higher = riskier); None when core metrics are missing.

    Core metrics (volatility, drawdown, VaR) are required — missing ones yield
    None instead of an invented score. Beta is optional and only ever ADDS
    risk for high values; a historical low-beta penalty (+5 in an old agent
    copy) was dropped: it contradicted the higher-is-riskier semantics.
    """
    required = (vol, dd, var)
    if any(value is None or not np.isfinite(value) for value in required):
        return None

    score = 0
    if vol >= 0.03:
        score += 30
    elif vol >= 0.02:
        score += 20
    elif vol >= 0.015:
        score += 10
    if dd >= 0.3:
        score += 30
    elif dd >= 0.2:
        score += 20
    elif dd >= 0.1:
        score += 10
    if abs(var) >= 0.05:
        score += 20
    elif abs(var) >= 0.03:
        score += 15
    elif abs(var) >= 0.02:
        score += 10
    if beta is not None:
        if beta >= 1.5:
            score += 20
        elif beta >= 1.2:
            score += 15
    return min(100, score)


def _score_to_level(score: float | None) -> str:
    if score is None:
        return "insufficient_data"
    if score >= 70:
        return "very_high"
    elif score >= 50:
        return "high"
    elif score >= 30:
        return "medium"
    elif score >= 15:
        return "low"
    else:
        return "very_low"


def _position_size(score: float | None) -> float | None:
    if score is None:
        return None
    if score >= 70:
        return 2.0
    elif score >= 50:
        return 5.0
    elif score >= 30:
        return 10.0
    elif score >= 15:
        return 15.0
    else:
        return 20.0


def _warnings(level: str, vol: float, dd: float, beta_status: str = "available") -> list:
    warnings = []
    if level in ["high", "very_high"]:
        warnings.append("High risk stock. Consider smaller position size.")
    if vol > 0.03:
        warnings.append(f"High daily volatility ({vol * 100:.1f}%).")
    if dd > 0.3:
        warnings.append(f"History of deep drawdowns ({dd * 100:.1f}%).")
    if beta_status != "available":
        warnings.append("Beta unavailable: aligned benchmark history is insufficient.")
    return warnings


# Public entry point shared by the pipeline agent and ReAct tools.
assess_symbol = _assess_symbol


def _minimal_risk(data: dict, symbol: str = "") -> dict:
    return {
        "symbol": data.get("symbol", symbol),
        "risk_score": None,
        "risk_level": "insufficient_data",
        "risk_score_status": "insufficient_data",
        "metrics": {"beta": None, "beta_status": "insufficient_data"},
        "position_recommendation": {
            "max_position_size": None,
            "status": "insufficient_data",
        },
        "warnings": ["Insufficient data for detailed risk assessment"],
    }
