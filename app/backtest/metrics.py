"""Performance metrics (V2 plan §7.1).

Full metric suite computed from an equity curve and the trade list: return,
risk-adjusted ratios, drawdown, tail risk, trade statistics, turnover and
cost share. All values are plain floats (JSON-safe); a metric that cannot be
computed (e.g. Sharpe with zero variance) is ``None``, never a fabricated 0.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


def compute_metrics(
    equity: pd.Series,
    *,
    trades: list[dict[str, Any]] | None = None,
    total_cost: float = 0.0,
    benchmark_equity: pd.Series | None = None,
    initial_cash: float = 1.0,
) -> dict[str, Any]:
    """Compute the standard metric suite for one backtest run."""
    equity = equity.dropna()
    if len(equity) < 2 or float(equity.iloc[0]) <= 0:
        return {}

    returns = equity.pct_change().dropna()
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1)
    years = max(len(equity) / TRADING_DAYS_PER_YEAR, 1e-9)
    cagr = float(equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1

    volatility = float(np.std(returns, ddof=1)) if len(returns) > 1 else None
    sharpe = _sharpe(returns)
    sortino = _sortino(returns)
    max_dd = _max_drawdown(equity)
    calmar = float(cagr / max_dd) if max_dd and max_dd > 0 else None
    cvar_95 = _cvar(returns)

    metrics: dict[str, Any] = {
        "total_return": round(total_return, 6),
        "cagr": round(cagr, 6),
        "volatility_annualized": (
            round(volatility * np.sqrt(TRADING_DAYS_PER_YEAR), 6)
            if volatility is not None
            else None
        ),
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": round(calmar, 6) if calmar is not None else None,
        "max_drawdown": round(max_dd, 6),
        "cvar_95_daily": cvar_95,
        "excess_vs_benchmark": _excess(equity, benchmark_equity),
    }

    metrics.update(_trade_stats(trades or []))
    metrics["total_cost"] = round(total_cost, 4)
    metrics["cost_ratio"] = round(total_cost / initial_cash, 6) if initial_cash > 0 else None
    return metrics


def _sharpe(returns: pd.Series) -> float | None:
    if len(returns) < 2:
        return None
    std = float(np.std(returns, ddof=1))
    if std <= np.finfo(float).eps:
        return None
    return round(float(np.mean(returns)) / std * np.sqrt(TRADING_DAYS_PER_YEAR), 6)


def _sortino(returns: pd.Series) -> float | None:
    if len(returns) < 2:
        return None
    downside = returns[returns < 0]
    if downside.empty:
        return None
    deviation = float(np.sqrt(np.mean(downside**2)))
    if deviation <= np.finfo(float).eps:
        return None
    return round(float(np.mean(returns)) / deviation * np.sqrt(TRADING_DAYS_PER_YEAR), 6)


def _max_drawdown(equity: pd.Series) -> float:
    cummax = equity.cummax()
    return float(((cummax - equity) / cummax).max())


def _cvar(returns: pd.Series, level: float = 0.95) -> float | None:
    if len(returns) < 20:
        return None
    cutoff = float(np.percentile(returns, (1 - level) * 100))
    tail = returns[returns <= cutoff]
    return round(float(np.mean(tail)), 6) if len(tail) else None


def _excess(equity: pd.Series, benchmark_equity: pd.Series | None) -> float | None:
    if benchmark_equity is None or len(benchmark_equity) < 2:
        return None
    strategy_return = float(equity.iloc[-1] / equity.iloc[0] - 1)
    benchmark_return = float(benchmark_equity.iloc[-1] / benchmark_equity.iloc[0] - 1)
    return round(strategy_return - benchmark_return, 6)


def _trade_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Win rate, profit factor and turnover from round-trip trades."""
    closes = [trade for trade in trades if trade.get("action") == "sell"]
    wins = [trade for trade in closes if trade.get("pnl", 0) > 0]
    losses = [trade for trade in closes if trade.get("pnl", 0) <= 0]

    gross_profit = sum(trade["pnl"] for trade in wins)
    gross_loss = abs(sum(trade["pnl"] for trade in losses))
    profit_factor = round(gross_profit / gross_loss, 6) if gross_loss > 0 else None

    return {
        "total_trades": len(closes),
        "win_rate": round(len(wins) / len(closes), 6) if closes else None,
        "profit_factor": profit_factor,
        "turnover_sides": len(trades),
    }
