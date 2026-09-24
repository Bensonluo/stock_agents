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
from app.backtest.null_benchmark import random_entry_null

STRATEGIES = (
    "sma_crossover",
    "rsi_strategy",
    "macd_strategy",
    "buy_and_hold",
    "technical_score",
)

STRATEGY_PARAMETERS: dict[str, frozenset[str]] = {
    "sma_crossover": frozenset({"sma_short", "sma_long"}),
    "rsi_strategy": frozenset({"rsi_period", "rsi_overbought", "rsi_oversold"}),
    "macd_strategy": frozenset({"fast_period", "slow_period", "signal_period"}),
    "buy_and_hold": frozenset(),
    "technical_score": frozenset({"score_threshold"}),
}

DEFAULT_PARAMS: dict[str, dict[str, float]] = {
    "sma_crossover": {"sma_short": 20, "sma_long": 50},
    "rsi_strategy": {"rsi_period": 14, "rsi_overbought": 70, "rsi_oversold": 30},
    "macd_strategy": {"fast_period": 12, "slow_period": 26, "signal_period": 9},
    "buy_and_hold": {},
    # 10 = the live pipeline's moderate_buy cutoff: any buy-ish technical
    # reading. The only knob — walk-forward can price the selection, DSR can
    # deflate it, calibration can score its hit rate.
    "technical_score": {"score_threshold": 10},
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
    # Random-entry Monte Carlo null ("signal or noise"); None when the run
    # opted out (null_iterations=0) or no meaningful null exists.
    null_benchmark: dict[str, Any] | None = None


def run_backtest(
    data: pd.DataFrame,
    *,
    strategy: str,
    cost_model: CostModel | None = None,
    initial_cash: float = 10_000.0,
    benchmark_data: pd.DataFrame | None = None,
    null_iterations: int = 0,
    null_seed: int = 42,
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
        null_iterations: Random-entry null draws for the signal-or-noise
            benchmark (0 disables — walk-forward parameter search keeps it
            off because every combo would pay the Monte Carlo cost).
        null_seed: Seed for the null draws; fixed default keeps the benchmark
            reproducible.
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
    if null_iterations > 0 and result.metrics.get("total_return") is not None:
        result.null_benchmark = random_entry_null(
            data,
            target,
            float(result.metrics["total_return"]),
            cost_model,
            initial_cash,
            iterations=null_iterations,
            seed=null_seed,
        )
        if result.null_benchmark is not None:
            result.metrics["null_benchmark"] = result.null_benchmark
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

    if strategy == "technical_score":
        # Replay of the decision layer's technical dimension score — the
        # only recommendation input that is a pure function of OHLCV.
        score = _technical_score_series(data)
        return (score >= float(params["score_threshold"])).astype(float)

    # buy_and_hold: in the market from the first executable bar.
    return pd.Series(1.0, index=data.index)


def _rsi(close: pd.Series, period: int) -> pd.Series:
    """Wilder RSI over the full series — the same definition the live daily
    engine (app.analysis.technical.daily._rsi) reports, so backtest fills
    correspond to signals the live pipeline would actually emit behind the
    same 30/70 thresholds. The old simple rolling mean produced jumpier
    values: identical thresholds, different trades. Vectorized Wilder =
    EMA(alpha=1/period) seeded by the SMA of the first `period` changes.
    """
    delta = close.diff().dropna()
    out = pd.Series(np.nan, index=close.index, dtype=float)
    if len(delta) < period:
        return out

    def _wilder(x: pd.Series) -> np.ndarray:
        seed = float(x.iloc[:period].mean())
        padded = np.concatenate([[seed], x.iloc[period:].to_numpy()])
        return pd.Series(padded).ewm(alpha=1 / period, adjust=False).mean().to_numpy()

    avg_gain = _wilder(delta.clip(lower=0.0))
    avg_loss = _wilder(-delta.clip(upper=0.0))
    # Values begin at bar index `period` (where the seed completes) — the
    # same first-value position the old rolling window produced.
    out.iloc[period:] = 100 - 100 / (1 + avg_gain / avg_loss)
    return out


def _technical_score_series(data: pd.DataFrame) -> pd.Series:
    """Vectorized replay of the live technical score (daily.py's −100..100).

    Same definition as ``calculate_sentiment(generate_signals(
    calculate_indicators(df[: t+1])))`` at every bar t: every window below
    looks only backwards, so each bar's score sees exactly the history the
    live pipeline would have had on that date. Windows are the live
    pipeline's constants (SMA 20/50, Wilder RSI 14, MACD 12/26/9 on
    adjust=True ewm, Bollinger 20±2σ, volume SMA 20) — deliberately not
    tunable: replaying the recommendation layer means using its numbers.

    Contribution table mirrors ``calculate_sentiment``: trend
    +30/+15/−15/−30, RSI oversold +20 / bullish +10 / bearish −10 /
    overbought −20 (in generate_signals' elif priority), MACD histogram
    sign ±20, Bollinger breaches ±15, volume confirmation ±15 only when
    ratio > 2 amplifies a non-zero score. Warm-up bars contribute 0 — the
    live pipeline's "unavailable → None" is the same no-vote.
    """
    close = data["Close"]
    score = pd.Series(0.0, index=close.index, dtype=float)

    sma_20 = close.rolling(20).mean()
    sma_50 = close.rolling(50).mean()
    have_trend = sma_20.notna() & sma_50.notna()
    strong_bull = have_trend & (close > sma_20) & (sma_20 > sma_50)
    bull = have_trend & (close > sma_20) & ~strong_bull
    strong_bear = have_trend & (close < sma_20) & (sma_20 < sma_50)
    bear = have_trend & (close < sma_20) & ~strong_bear
    score = score + 30.0 * strong_bull + 15.0 * bull - 30.0 * strong_bear - 15.0 * bear

    rsi = _rsi(close, 14)
    score = score + pd.Series(
        np.select(
            [rsi > 70, rsi > 60, rsi < 30, rsi < 40],
            [-20.0, 10.0, 20.0, -10.0],
            default=0.0,
        ),
        index=close.index,
    )

    macd_line = close.ewm(span=12).mean() - close.ewm(span=26).mean()
    signal_line = macd_line.ewm(span=9).mean()
    hist = macd_line - signal_line
    # The live elif chain fires bearish whenever the histogram is not > 0.
    score = score + 20.0 * (hist > 0) - 20.0 * (hist <= 0)

    std_20 = close.rolling(20).std()
    upper = sma_20 + 2.0 * std_20
    lower = sma_20 - 2.0 * std_20
    score = score + 15.0 * (close < lower) - 15.0 * (close > upper)

    if "Volume" in data.columns:
        vol_sma = data["Volume"].rolling(20).mean()
        # ratio > 2 implies a positive denominator; masked elsewhere so a
        # zero/NaN SMA (warm-up, dead tape) never fabricates a confirmation.
        ratio = data["Volume"] / vol_sma.mask(~(vol_sma > 0))
        confirm = ratio > 2
        score = score + 15.0 * (confirm & (score > 0)) - 15.0 * (confirm & (score < 0))

    return score


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
