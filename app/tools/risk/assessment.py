"""Risk assessment tools. Extracted from app/agents/risk_agent.py"""

from typing import Any

import numpy as np
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.utils.logging import get_logger

logger = get_logger(__name__)

MIN_BETA_OBSERVATIONS = 20


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
                results[symbol] = _minimal_risk(data, symbol)
                continue

            returns = np.diff(closes) / closes[:-1]
            volatility = float(np.std(returns))
            var_95 = float(np.percentile(returns, 5))
            var_99 = float(np.percentile(returns, 1))
            max_dd = _max_drawdown(closes)
            downside = _downside_risk(returns)
            benchmark_history = _get_benchmark_history(data)
            beta = _calculate_beta_from_histories(hist, benchmark_history)
            risk_score = _calculate_score(volatility, max_dd, var_95, beta)
            risk_level = _score_to_level(risk_score)
            beta_status = "available" if beta is not None else "insufficient_data"

            results[symbol] = {
                "symbol": symbol,
                "risk_score": risk_score,
                "risk_level": risk_level,
                "risk_score_status": "complete" if beta is not None else "partial",
                "metrics": {
                    "volatility": volatility,
                    "volatility_annualized": float(volatility * np.sqrt(252)),
                    "var_95": var_95,
                    "var_99": var_99,
                    "max_drawdown": max_dd,
                    "downside_risk": downside,
                    "beta": beta,
                    "beta_status": beta_status,
                },
                "position_recommendation": {
                    "max_position_size": _position_size(risk_score) if beta is not None else None,
                    "stop_loss_percentage": float(volatility * 2 * 100),
                    "status": "available" if beta is not None else "insufficient_data",
                },
                "warnings": _warnings(risk_level, volatility, max_dd, beta_status),
            }
        except Exception as e:
            logger.error(f"Risk assessment failed for {symbol}: {e}")
            results[symbol] = _minimal_risk(data, symbol)

    return results


def _max_drawdown(prices: np.ndarray) -> float:
    cummax = np.maximum.accumulate(prices)
    drawdown = (cummax - prices) / cummax
    return float(np.max(drawdown))


def _downside_risk(returns: np.ndarray) -> float:
    neg = returns[returns < 0]
    return float(np.std(neg)) if len(neg) > 0 else 0.0


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


def _aligned_returns(stock_history: dict, benchmark_history: dict) -> tuple[np.ndarray, np.ndarray]:
    """Calculate returns over identical dated intervals for stock and benchmark."""
    stock_dates = stock_history.get("dates", [])
    stock_closes = stock_history.get("close", [])
    benchmark_dates = benchmark_history.get("dates", [])
    benchmark_closes = benchmark_history.get("close", [])

    if len(stock_dates) != len(stock_closes) or len(benchmark_dates) != len(benchmark_closes):
        return np.array([]), np.array([])

    try:
        stock_by_date = {
            str(day): float(price)
            for day, price in zip(stock_dates, stock_closes, strict=True)
            if np.isfinite(float(price)) and float(price) > 0
        }
        benchmark_by_date = {
            str(day): float(price)
            for day, price in zip(benchmark_dates, benchmark_closes, strict=True)
            if np.isfinite(float(price)) and float(price) > 0
        }
    except (TypeError, ValueError):
        return np.array([]), np.array([])

    common_dates = sorted(stock_by_date.keys() & benchmark_by_date.keys())
    if len(common_dates) < 2:
        return np.array([]), np.array([])

    stock_prices = np.array([stock_by_date[day] for day in common_dates])
    benchmark_prices = np.array([benchmark_by_date[day] for day in common_dates])
    return np.diff(stock_prices) / stock_prices[:-1], np.diff(benchmark_prices) / benchmark_prices[
        :-1
    ]


def _calculate_beta(
    stock_returns: np.ndarray,
    benchmark_returns: np.ndarray | None,
    min_observations: int = MIN_BETA_OBSERVATIONS,
) -> float | None:
    """Calculate beta from paired returns, or return None when evidence is inadequate."""
    if benchmark_returns is None:
        return None

    stock = np.asarray(stock_returns, dtype=float)
    benchmark = np.asarray(benchmark_returns, dtype=float)
    if stock.ndim != 1 or benchmark.ndim != 1 or len(stock) != len(benchmark):
        return None

    finite = np.isfinite(stock) & np.isfinite(benchmark)
    stock = stock[finite]
    benchmark = benchmark[finite]
    if len(stock) < min_observations:
        return None

    benchmark_variance = float(np.var(benchmark, ddof=1))
    if not np.isfinite(benchmark_variance) or benchmark_variance <= np.finfo(float).eps:
        return None

    covariance = float(np.cov(stock, benchmark, ddof=1)[0, 1])
    beta = covariance / benchmark_variance
    return float(beta) if np.isfinite(beta) else None


def _calculate_beta_from_histories(
    stock_history: dict, benchmark_history: dict | None
) -> float | None:
    if not benchmark_history:
        return None
    stock_returns, benchmark_returns = _aligned_returns(stock_history, benchmark_history)
    return _calculate_beta(stock_returns, benchmark_returns)


def _calculate_score(vol: float, dd: float, var: float, beta: float | None) -> float:
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


def _score_to_level(score: float) -> str:
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


def _position_size(score: float) -> float:
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
