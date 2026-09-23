"""Experiment manifest (V2 plan §7.1, §9 Phase 3).

Any backtest result must be reproducible: the manifest pins the data (hash),
the parameters, the cost model, the code commit and how many configurations
were tried — the overfitting telemetry.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.backtest.costs import CostModel

REPO_ROOT = Path(__file__).resolve().parents[2]


def build_manifest(
    *,
    symbol: str,
    strategy: str,
    params: dict[str, Any],
    start: str,
    end: str,
    data: pd.DataFrame,
    cost_model: CostModel,
    configs_tested: int = 1,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Manifest for one backtest (or one walk-forward experiment)."""
    return {
        "schema_version": "1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "symbol": symbol,
        "strategy": strategy,
        "params": params,
        "start": start,
        "end": end,
        "bars": int(len(data)),
        "data_sha256": hash_dataframe(data),
        "cost_model": _plain(cost_model),
        "configs_tested": configs_tested,
        "code_commit": current_commit(),
        "extra": extra or {},
    }


def hash_dataframe(data: pd.DataFrame) -> str:
    """Stable content hash of the price frame (index included)."""
    payload = data.to_csv(index=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def current_commit(repo: Path = REPO_ROOT) -> str | None:
    """HEAD commit hash, or None outside a git repo / without git."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _plain(value: Any) -> Any:
    """Dataclasses/dates -> JSON-safe structures."""
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    if value is not None and not isinstance(value, str | int | float | bool):
        return json.loads(json.dumps(value, default=str))
    return value
