"""Deterministic backtest engine (V2 plan §7.1).

Rules enforced here (the minimum backtest standard):
- A signal computed on bar ``t``'s close is executed at bar ``t+1``'s open.
  No run may buy and sell on the same close that generated the signal.
- Every fill pays the cost model (commission, minimum fee, taxes, slippage).
- Indicators are NaN before their warm-up completes; a NaN signal means "no
  position", never "neutral filler".
- The same data + params + cost model always produce the same result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from app.backtest.costs import CostModel
from app.backtest.metrics import compute_metrics

STRATEGIES = ("sma_crossover", "rsi_strategy", "macd_strategy", "buy_and_hold")

STRATEGY_PARAMETERS: dict[str, frozenset[str]] = {
    "sma_crossover": frozenset({"sma_short", "sma_long"}),
    "rsi_strategy": frozenset({"rsi_period", "rsi_overbought", "rsi_oversold"}),
    "macd_strategy": frozenset({"fast_period", "slow_period", "signal_period"}),
    "buy_and_hold": frozenset(),
}

DEFAULT_PARAMS: dict[str, dict[str, float]] = {
    "sma_crossover": {"sma_short": 20, "sma_long": 50},
    "rsi_strategy": {"rsi_period": 14, "rsi_overbought": 70, "rsi_oversold": 30},
    "macd_strategy": {"fast_period": 12, "slow_period": 26, "signal_period": 9},
    "buy_and_hold": {},
}


@dataclass
class BacktestResult:
    """Everything one run produced; equity stays a Series for further math."""

    strategy: str
    params: dict[str, Any]
    equity: pd.Series | None = None
    benchmark_equity: pd.Series | None = None
    trades: list[dict[str, Any]] = field(default_factory=list)
    total_cost: float = 0.0
    bars: int = 0
    metrics: dict[str, Any] = field(default_factory=dict)


def run_backtest(
    data: pd.DataFrame,
    *,
    strategy: str,
    cost_model: CostModel | None = None,
    initial_cash: float = 10_000.0,
    benchmark_data: pd.DataFrame | None = None,
    **params: Any,
) -> BacktestResult:
    """Run one deterministic backtest over OHLCV data.

    Args:
        data: Daily bars with a DatetimeIndex and at least ``Open``/``Close``.
        strategy: One of :data:`STRATEGIES`.
        cost_model: Transaction costs; defaults to a plain commission model.
        initial_cash: Starting equity.
        benchmark_data: Optional OHLCV for the buy-and-hold benchmark, aligned
            to the same dates for the excess-return metric.
        **params: Strategy parameters; unknown names are rejected.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy: {strategy}")
    unknown = set(params) - STRATEGY_PARAMETERS[strategy]
    if unknown:
        raise ValueError(f"Unknown parameter for {strategy}: {sorted(unknown)[0]}")
    if data.empty or "Open" not in data or "Close" not in data:
        raise ValueError("data must contain Open and Close columns")

    cost_model = cost_model or CostModel()
    data = _sanitize(data)
    merged = {**DEFAULT_PARAMS[strategy], **params}
    target = _target_position(data, strategy, merged)

    equity, trades, total_cost = _simulate(data, target, cost_model, initial_cash)
    benchmark_equity = None
    if benchmark_data is not None and not benchmark_data.empty:
        benchmark_equity, _, _ = _simulate(
            benchmark_data.reindex(data.index).ffill(),
            pd.Series(1, index=data.index),
            cost_model,
            initial_cash,
        )

    result = BacktestResult(
        strategy=strategy,
        params=merged,
        equity=equity,
        benchmark_equity=benchmark_equity,
        trades=trades,
        total_cost=total_cost,
        bars=int(len(data)),
    )
    result.metrics = compute_metrics(
        equity,
        trades=trades,
        total_cost=total_cost,
        benchmark_equity=benchmark_equity,
        initial_cash=initial_cash,
    )
    return result


# ----------------------------------------------------------------------
# Signals: computed on close of bar t; execution happens at t+1 open.
# ----------------------------------------------------------------------


def _sanitize(data: pd.DataFrame) -> pd.DataFrame:
    """Chronological order, one bar per timestamp — an unsorted or duplicated
    index is itself a look-ahead bug, so it is normalized deterministically."""
    if not data.index.is_monotonic_increasing:
        data = data.sort_index()
    if data.index.has_duplicates:
        data = data[~data.index.duplicated(keep="last")]
    return data


def _target_position(data: pd.DataFrame, strategy: str, params: dict[str, Any]) -> pd.Series:
    close = data["Close"]
    if strategy == "sma_crossover":
        short = close.rolling(int(params["sma_short"])).mean()
        long = close.rolling(int(params["sma_long"])).mean()
        state = (short > long).astype(float)
        state[short.isna() | long.isna()] = 0.0
        return state

    if strategy == "macd_strategy":
        macd_line = (
            close.ewm(span=int(params["fast_period"]), adjust=False).mean()
            - close.ewm(span=int(params["slow_period"]), adjust=False).mean()
        )
        signal_line = macd_line.ewm(span=int(params["signal_period"]), adjust=False).mean()
        state = (macd_line > signal_line).astype(float)
        # MACD needs slow+signal bars before it means anything.
        state.iloc[: int(params["slow_period"]) + int(params["signal_period"])] = 0.0
        return state

    if strategy == "rsi_strategy":
        rsi = _rsi(close, int(params["rsi_period"]))
        entry = rsi < float(params["rsi_oversold"])
        exit_ = rsi > float(params["rsi_overbought"])
        return _state_machine(entry, exit_)

    # buy_and_hold: in the market from the first executable bar.
    return pd.Series(1.0, index=data.index)


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rsi = 100 - (100 / (1 + gain / loss))
    return rsi


def _state_machine(entry: pd.Series, exit_: pd.Series) -> pd.Series:
    """RSI-style state: enter on oversold, hold until overbought exit."""
    state = np.zeros(len(entry))
    current = 0.0
    for i, (enter, leave) in enumerate(zip(entry.tolist(), exit_.tolist(), strict=True)):
        if pd.isna(enter) or pd.isna(leave):
            current = 0.0
        elif current == 0.0 and bool(enter):
            current = 1.0
        elif current == 1.0 and bool(leave):
            current = 0.0
        state[i] = current
    return pd.Series(state, index=entry.index)


# ----------------------------------------------------------------------
# Simulation: fills at the NEXT bar's open, costs always applied.
# ----------------------------------------------------------------------


def _simulate(
    data: pd.DataFrame,
    target: pd.Series,
    cost_model: CostModel,
    initial_cash: float,
) -> tuple[pd.Series, list[dict[str, Any]], float]:
    opens = data["Open"]
    closes = data["Close"]
    # Position held DURING bar t comes from the signal of bar t-1.
    held = target.shift(1).fillna(0.0).tolist()

    cash = float(initial_cash)
    shares = 0.0
    equity_values: list[float] = []
    trades: list[dict[str, Any]] = []
    total_cost = 0.0
    open_trade: dict[str, Any] | None = None

    for i in range(len(data)):
        date = data.index[i]
        want_in = held[i] > 0
        open_price = float(opens.iloc[i])

        if want_in and shares == 0.0 and np.isfinite(open_price) and open_price > 0:
            fill_price = cost_model.buy_price(open_price)
            traded_value = cash / (1 + cost_model.commission_rate + cost_model.transfer_fee)
            shares = traded_value / fill_price
            cost = cost_model.buy_cost(traded_value)
            total_cost += cost
            cash -= traded_value + cost
            open_trade = {
                "action": "buy",
                "date": str(date),
                "price": round(fill_price, 6),
                "cost": round(cost, 6),
            }
        elif not want_in and shares > 0.0 and np.isfinite(open_price) and open_price > 0:
            fill_price = cost_model.sell_price(open_price)
            traded_value = shares * fill_price
            cost = cost_model.sell_cost(traded_value)
            total_cost += cost
            proceeds = traded_value - cost
            cash += proceeds
            if open_trade is not None:
                trades.append(open_trade)
                trades.append(
                    {
                        "action": "sell",
                        "date": str(date),
                        "price": round(fill_price, 6),
                        "cost": round(cost, 6),
                        "pnl": round(proceeds - _entry_value(open_trade, shares), 6),
                    }
                )
            shares = 0.0
            open_trade = None

        equity_values.append(cash + shares * float(closes.iloc[i]))

    # A position still open at the end is force-liquidated at the final
    # close (with exit costs) so trade statistics cover every round trip.
    if shares > 0.0 and open_trade is not None:
        final_price = cost_model.sell_price(float(closes.iloc[-1]))
        traded_value = shares * final_price
        cost = cost_model.sell_cost(traded_value)
        total_cost += cost
        proceeds = traded_value - cost
        trades.append(open_trade)
        trades.append(
            {
                "action": "sell",
                "date": str(data.index[-1]),
                "price": round(final_price, 6),
                "cost": round(cost, 6),
                "pnl": round(proceeds - _entry_value(open_trade, shares), 6),
                "liquidated_at_end": True,
            }
        )
        cash += proceeds
        shares = 0.0
        equity_values[-1] = cash

    equity = pd.Series(equity_values, index=data.index, dtype="float64")
    return equity, trades, total_cost


def _entry_value(open_trade: dict[str, Any], shares: float) -> float:
    """Cash that went into the position (ex-entry costs)."""
    return shares * open_trade["price"]
