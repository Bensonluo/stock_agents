"""Risk engine (V2 plan §3.2.G, §5.1).

Deterministic risk computations shared by the pipeline and ReAct paths.
Loss-based metrics (VaR/CVaR, drawdown, downside deviation) use historical
daily returns; relative metrics (beta/alpha/R²) require explicitly supplied
benchmark history — nothing is substituted with a default benchmark.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from app.analysis.technical.engine import make_evidence
from app.domain.schemas import MetricEvidence

# Beta/alpha need at least this many aligned return observations.
MIN_BETA_OBSERVATIONS = 20
# Rolling window (days) for the short-term volatility regime percentile.
VOL_REGIME_WINDOW = 20

# Market shock scenarios for stress estimates (fractional moves).
MARKET_SHOCKS: dict[str, float] = {
    "market_-5pct": -0.05,
    "market_-10pct": -0.10,
    "market_-20pct": -0.20,
}


def to_returns(closes: list[float] | np.ndarray) -> np.ndarray:
    """Daily simple returns from a close series."""
    prices = np.asarray(closes, dtype=float)
    if prices.ndim != 1 or len(prices) < 2:
        return np.array([])
    return prices[1:] / prices[:-1] - 1


def max_drawdown(closes: list[float] | np.ndarray) -> float:
    """Peak-to-trough decline over the whole series (positive fraction)."""
    prices = np.asarray(closes, dtype=float)
    if len(prices) < 2:
        return 0.0
    cummax = np.maximum.accumulate(prices)
    return float(np.max((cummax - prices) / cummax))


def downside_deviation(returns: np.ndarray) -> float:
    """Standard deviation of negative returns only."""
    negative = returns[returns < 0]
    return float(np.std(negative)) if len(negative) > 0 else 0.0


def var_historical(returns: np.ndarray, level: float = 0.95) -> float | None:
    """Historical VaR as a negative return quantile; None without enough data."""
    if len(returns) < 20:
        return None
    return float(np.percentile(returns, (1 - level) * 100))


def cvar_historical(returns: np.ndarray, level: float = 0.95) -> float | None:
    """Historical CVaR (expected shortfall): mean of the tail beyond VaR."""
    if len(returns) < 20:
        return None
    cutoff = float(np.percentile(returns, (1 - level) * 100))
    tail = returns[returns <= cutoff]
    return float(np.mean(tail)) if len(tail) else None


def sortino_ratio(
    returns: np.ndarray, *, periods_per_year: int = 252, target: float = 0.0
) -> float | None:
    """Annualized Sortino ratio; None when downside deviation is zero."""
    if len(returns) < 20:
        return None
    downside = returns[returns < target] - target
    deviation = float(np.sqrt(np.mean(downside**2))) if len(downside) else 0.0
    if deviation <= np.finfo(float).eps:
        return None
    excess = float(np.mean(returns)) - target
    return round(excess / deviation * np.sqrt(periods_per_year), 4)


def volatility_percentile(returns: np.ndarray, window: int = VOL_REGIME_WINDOW) -> float | None:
    """Percentile of current rolling volatility vs its own history (0-1)."""
    if len(returns) <= window:
        return None
    series = pd.Series(returns)
    rolling_vol = series.rolling(window).std().dropna()
    if len(rolling_vol) < 2:
        return None
    current = float(rolling_vol.iloc[-1])
    return round(float((rolling_vol < current).mean()), 4)


def aligned_returns(stock_history: dict, benchmark_history: dict) -> tuple[np.ndarray, np.ndarray]:
    """Returns over identical dated intervals for stock and benchmark."""
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
    return to_returns(stock_prices), to_returns(benchmark_prices)


def calculate_beta(
    stock_returns: np.ndarray,
    benchmark_returns: np.ndarray | None,
    min_observations: int = MIN_BETA_OBSERVATIONS,
) -> float | None:
    """Beta from paired returns; None when evidence is inadequate."""
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


def relative_risk_metrics(
    stock_returns: np.ndarray, benchmark_returns: np.ndarray
) -> dict[str, float | None]:
    """Beta, annualized alpha, R² and correlation from paired returns.

    Any metric whose evidence is inadequate comes back as None instead of a
    default value.
    """
    stock = np.asarray(stock_returns, dtype=float)
    benchmark = np.asarray(benchmark_returns, dtype=float)
    finite = np.isfinite(stock) & np.isfinite(benchmark)
    stock, benchmark = stock[finite], benchmark[finite]
    if len(stock) < MIN_BETA_OBSERVATIONS:
        return {"beta": None, "alpha_annualized": None, "r_squared": None, "correlation": None}

    beta = calculate_beta(stock, benchmark)
    if beta is None:
        return {"beta": None, "alpha_annualized": None, "r_squared": None, "correlation": None}

    correlation = float(np.corrcoef(stock, benchmark)[0, 1])
    # Annualized excess of the stock over what beta explains of the benchmark.
    alpha = float((np.mean(stock) - beta * np.mean(benchmark)) * 252)

    return {
        "beta": round(beta, 4),
        "alpha_annualized": round(alpha, 4),
        "r_squared": round(correlation**2, 4),
        "correlation": round(correlation, 4),
    }


def stress_scenarios(beta: float | None) -> dict[str, Any]:
    """Estimated stock impact for market shocks, via beta.

    Without beta the scenarios are honestly unavailable — a guessed impact
    would be fabricated precision.
    """
    if beta is None:
        return {"status": "insufficient_data", "scenarios": {}}
    return {
        "status": "available",
        "scenarios": {name: round(beta * shock, 4) for name, shock in MARKET_SHOCKS.items()},
    }


def correlation_matrix(histories: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Pairwise return correlations across symbols with aligned dates."""
    series: dict[str, pd.Series] = {}
    for symbol, history in histories.items():
        dates = list(history.get("dates") or [])
        closes = list(history.get("close") or [])
        if len(dates) == len(closes) and len(dates) > 1:
            prices = pd.Series(closes, index=pd.to_datetime(dates), dtype="float64")
            returns = prices.pct_change().dropna()
            if len(returns) >= MIN_BETA_OBSERVATIONS:
                series[symbol] = returns

    symbols = sorted(series)
    if len(symbols) < 2:
        return {"status": "insufficient_data", "pairs": {}}

    frame = pd.DataFrame(series).dropna()
    if len(frame) < MIN_BETA_OBSERVATIONS:
        return {"status": "insufficient_data", "pairs": {}}

    correlation = frame.corr()
    pairs = {
        f"{a}|{b}": round(float(correlation.loc[a, b]), 4)
        for i, a in enumerate(symbols)
        for b in symbols[i + 1 :]
    }
    return {
        "status": "available",
        "pairs": pairs,
        "aligned_days": int(len(frame)),
    }


def concentration_hhi(weights: Mapping[str, float]) -> float | None:
    """Herfindahl-Hirschman concentration index of portfolio weights (0-1)."""
    values = [float(weight) for weight in weights.values() if float(weight) > 0]
    total = sum(values)
    if total <= 0:
        return None
    shares = [value / total for value in values]
    return round(sum(share**2 for share in shares), 4)


def risk_evidence(
    *,
    symbol: str,
    metrics: Mapping[str, Any],
    as_of: Any,
    source: str = "market_data_history",
) -> list[MetricEvidence]:
    """Evidence records for the headline risk numbers that exist."""
    evidence: list[MetricEvidence] = []
    cutoff = _as_cutoff(as_of)
    if cutoff is None:
        return evidence

    specs = (
        (
            "volatility_annualized",
            "volatility_annualized",
            "ratio",
            "std(daily_returns) * sqrt(252)",
            {},
        ),
        (
            "beta",
            "beta",
            "ratio",
            "cov(r_stock, r_benchmark) / var(r_benchmark)",
            {"estimator": "ols"},
        ),
        (
            "cvar_95",
            "cvar_95",
            "ratio",
            "mean(returns <= quantile(returns, 0.05))",
            {"level": 0.95},
        ),
        (
            "sortino",
            "sortino",
            "ratio",
            "(mean(r) / downside_deviation(r)) * sqrt(252)",
            {"target": 0.0},
        ),
    )
    for key, name, unit, formula, params in specs:
        value = metrics.get(key)
        if value is None:
            continue
        evidence.append(
            make_evidence(
                symbol=symbol,
                name=name,
                value=float(value),
                unit=unit,
                cutoff=cutoff,
                source=source,
                formula=formula,
                params=params,
            )
        )
    return evidence


def _as_cutoff(as_of: Any) -> Any:
    """Accept ISO strings or datetimes; None when nothing usable is given."""
    if isinstance(as_of, date):
        return as_of
    if isinstance(as_of, str) and as_of:
        try:
            return date.fromisoformat(as_of[:10])
        except ValueError:
            return None
    return None
