"""V2 backtest layer (V2 plan §5.1): costs, engine, metrics, walk-forward, manifest."""

from app.backtest.costs import CN_STOCK, US_STOCK, ZERO, CostModel
from app.backtest.engine import STRATEGIES, STRATEGY_PARAMETERS, BacktestResult, run_backtest
from app.backtest.manifest import build_manifest, current_commit, hash_dataframe
from app.backtest.metrics import compute_metrics
from app.backtest.walkforward import walk_forward

__all__ = [
    "CN_STOCK",
    "BacktestResult",
    "STRATEGIES",
    "STRATEGY_PARAMETERS",
    "US_STOCK",
    "ZERO",
    "CostModel",
    "build_manifest",
    "compute_metrics",
    "current_commit",
    "hash_dataframe",
    "run_backtest",
    "walk_forward",
]
