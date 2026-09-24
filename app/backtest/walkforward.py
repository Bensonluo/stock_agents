"""Walk-forward evaluation with parameter neighborhoods (V2 plan §7.1/§7.2).

Rolling train/test split: for each window the best parameter set is chosen on
the TRAIN segment only, then run once on the unseen TEST segment. The output
reports every window (including failures), the parameter choices across
windows (stability), and how many configurations were tested — the
overfitting telemetry the methodology requires.

The aggregate also carries the Deflated Sharpe Ratio (Bailey & López de
Prado, JPM 2014): the winner of a max-of-N configuration search must clear
the expected maximum of N noise trials, not zero. ``configs_tested`` says
how much selection pressure was applied; the DSR prices it.
"""

from __future__ import annotations

import itertools
from typing import Any

import pandas as pd

from app.backtest.costs import CostModel
from app.backtest.dsr import deflated_sharpe_ratio
from app.backtest.engine import run_backtest


def walk_forward(
    data: pd.DataFrame,
    *,
    strategy: str,
    param_grid: dict[str, list[Any]],
    train_bars: int,
    test_bars: int,
    cost_model: CostModel | None = None,
    initial_cash: float = 10_000.0,
    selection_metric: str = "sharpe",
) -> dict[str, Any]:
    """Rolling walk-forward over ``param_grid``.

    Args:
        data: Daily OHLCV frame.
        strategy: Strategy name (see engine.STRATEGIES).
        param_grid: Parameter name -> list of candidate values. The tested
            configuration count is the cartesian product.
        train_bars / test_bars: Window sizes in bars.
        selection_metric: Metric maximized on the train segment
            (``sharpe`` or ``cagr``); metrics that are None rank as -infinity.
    """
    if train_bars <= 0 or test_bars <= 0:
        raise ValueError("train_bars and test_bars must be positive")
    if len(data) < train_bars + test_bars:
        return {
            "windows": [],
            "aggregate": {"error": "not enough data for one train+test window"},
            "configs_tested": 0,
        }

    combos = [
        dict(zip(param_grid, values, strict=True))
        for values in itertools.product(*param_grid.values())
    ]
    windows: list[dict[str, Any]] = []
    # DSR inputs: the delivered OOS return stream (concatenated across test
    # segments) and the per-configuration train Sharpes (the selection pool).
    oos_returns: list[float] = []
    trial_sharpes: list[float] = []
    start = 0
    while start + train_bars + test_bars <= len(data):
        train = data.iloc[start : start + train_bars]
        test = data.iloc[start + train_bars : start + train_bars + test_bars]

        best_params, best_score, train_results = _select_params(
            train, strategy, combos, cost_model, initial_cash, selection_metric
        )
        oos = run_backtest(
            test, strategy=strategy, cost_model=cost_model, initial_cash=initial_cash, **best_params
        )
        windows.append(
            {
                "test_start": str(test.index[0]),
                "test_end": str(test.index[-1]),
                "chosen_params": best_params,
                "train_score": best_score,
                "train_results": train_results,
                "test_metrics": oos.metrics,
                "test_return": oos.metrics.get("total_return"),
            }
        )
        if oos.equity is not None:
            oos_returns.extend(float(r) for r in oos.equity.pct_change().dropna())
        trial_sharpes.extend(t["sharpe"] for t in train_results if t["sharpe"] is not None)
        start += test_bars

    return {
        "windows": windows,
        "aggregate": _aggregate(windows, param_grid, oos_returns, trial_sharpes, len(combos)),
        "configs_tested": len(combos) * len(windows),
    }


def _select_params(
    train: pd.DataFrame,
    strategy: str,
    combos: list[dict[str, Any]],
    cost_model: CostModel | None,
    initial_cash: float,
    selection_metric: str,
) -> tuple[dict[str, Any], float | None, list[dict[str, Any]]]:
    """Evaluate every combo on the train segment; return the best + all scores."""
    best_params: dict[str, Any] = combos[0]
    best_score = -float("inf")
    train_results: list[dict[str, Any]] = []

    for combo in combos:
        result = run_backtest(
            train, strategy=strategy, cost_model=cost_model, initial_cash=initial_cash, **combo
        )
        score = result.metrics.get(selection_metric)
        sharpe = result.metrics.get("sharpe")
        numeric = float(score) if isinstance(score, int | float) else -float("inf")
        # "sharpe" is recorded regardless of the selection metric: the DSR's
        # trial pool is the dispersion of train Sharpes across configurations.
        train_results.append(
            {
                "params": combo,
                "score": None if score is None else float(score),
                "sharpe": float(sharpe) if isinstance(sharpe, int | float) else None,
            }
        )
        if numeric > best_score:
            best_score, best_params = numeric, combo

    return best_params, (None if best_score == -float("inf") else best_score), train_results


def _aggregate(
    windows: list[dict[str, Any]],
    param_grid: dict[str, list[Any]],
    oos_daily_returns: list[float],
    trial_sharpes: list[float],
    n_configurations: int,
) -> dict[str, Any]:
    """Out-of-sample aggregates including the failures, not just the mean.

    ``oos_daily_returns`` is the concatenated per-bar return stream of the
    delivered (test-segment) equity curves — deliberately a distinct name
    from the per-window total-return local below, which it must not shadow.
    """
    if not windows:
        return {"error": "no complete windows"}

    oos_returns = [w["test_metrics"].get("total_return") for w in windows]
    oos_sharpes = [w["test_metrics"].get("sharpe") for w in windows]
    numeric_returns = [r for r in oos_returns if isinstance(r, int | float)]
    numeric_sharpes = [s for s in oos_sharpes if isinstance(s, int | float)]

    choices_by_key: dict[tuple, int] = {}
    for window in windows:
        key = tuple((name, window["chosen_params"].get(name)) for name in sorted(param_grid))
        choices_by_key[key] = choices_by_key.get(key, 0) + 1
    modal_count = max(choices_by_key.values()) if choices_by_key else 0

    worst = min(
        (w for w in windows if isinstance(w["test_return"], int | float)),
        key=lambda w: w["test_return"],
        default=None,
    )

    return {
        "windows_run": len(windows),
        "oos_return_mean": (
            round(sum(numeric_returns) / len(numeric_returns), 6) if numeric_returns else None
        ),
        "oos_sharpe_mean": (
            round(sum(numeric_sharpes) / len(numeric_sharpes), 6) if numeric_sharpes else None
        ),
        "losing_windows": sum(1 for r in numeric_returns if r < 0),
        "worst_window": (
            {k: worst[k] for k in ("test_start", "test_end", "test_return")} if worst else None
        ),
        "param_stability": round(modal_count / len(windows), 4) if windows else None,
        "deflated_sharpe": deflated_sharpe_ratio(
            oos_daily_returns, trial_sharpes, n_configurations
        ),
    }
