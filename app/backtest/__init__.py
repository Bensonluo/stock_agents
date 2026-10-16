"""V2 backtest layer (V2 plan §5.1): costs, engine, metrics, walk-forward, manifest."""

from app.backtest.calibration import calibrate_signals
from app.backtest.costs import CN_STOCK, US_STOCK, ZERO, CostModel
from app.backtest.engine import STRATEGIES, STRATEGY_PARAMETERS, run_backtest
from app.backtest.manifest import build_manifest, hash_dataframe
from app.backtest.point_in_time import stamp_visibility, visible_from
from app.backtest.walkforward import walk_forward

__all__ = [
    "CN_STOCK",
    "STRATEGIES",
    "STRATEGY_PARAMETERS",
    "US_STOCK",
    "ZERO",
    "CostModel",
    "build_manifest",
    "calibrate_signals",
    "hash_dataframe",
    "run_backtest",
    "stamp_visibility",
    "visible_from",
    "walk_forward",
]
