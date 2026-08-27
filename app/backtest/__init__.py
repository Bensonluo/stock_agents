"""V2 backtest layer (V2 plan §5.1): costs, engine, metrics, walk-forward, manifest."""

from app.backtest.calibration import calibrate_signals, wilson_lower_bound
from app.backtest.costs import CN_STOCK, US_STOCK, ZERO, CostModel
from app.backtest.engine import STRATEGIES, STRATEGY_PARAMETERS, BacktestResult, run_backtest
from app.backtest.manifest import build_manifest, current_commit, hash_dataframe
from app.backtest.metrics import compute_metrics
from app.backtest.point_in_time import (
    latest_visible_value,
    stamp_visibility,
    visible_from,
    visible_values_at,
)
from app.backtest.walkforward import walk_forward

__all__ = [
    "BacktestResult",
    "CN_STOCK",
    "STRATEGIES",
    "STRATEGY_PARAMETERS",
    "US_STOCK",
    "ZERO",
    "CostModel",
    "build_manifest",
    "calibrate_signals",
    "compute_metrics",
    "current_commit",
    "hash_dataframe",
    "latest_visible_value",
    "run_backtest",
    "stamp_visibility",
    "visible_from",
    "visible_values_at",
    "walk_forward",
    "wilson_lower_bound",
]
