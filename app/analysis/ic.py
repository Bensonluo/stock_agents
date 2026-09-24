"""Cross-sectional Information Coefficient of the decision layer.

The decision agent emits per-symbol composite scores — an ordinal
cross-sectional signal. This module scores that signal against realized
forward returns the way production quant research does: Spearman rank
IC per historical run, aggregated into ICIR (mean IC / std IC) with a
t-statistic (Grinold & Kahn). "How good were our past recommendations?"
becomes measurable instead of self-assessed.

Pure functions only — network access and storage live in
``app.services.ic_service``.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# Rank correlation on fewer than three points is numerically meaningless.
MIN_IC_SYMBOLS = 3
# ICIR needs a dispersion estimate; a single run has none.
MIN_IC_RUNS = 2


def decision_scores(result: dict[str, Any]) -> dict[str, float]:
    """Extract ``{symbol: composite score}`` from a stored analysis result.

    Tolerates both stored shapes (pipeline ``decision.decisions`` keyed by
    symbol; response-style top-level ``decisions`` list) and both score keys
    (``score`` from the decision agent, ``composite_score`` from derived
    recommendations). Unscored entries (zero-evidence runs emit ``None``)
    are skipped — missing evidence is not a neutral vote.
    """
    scores: dict[str, float] = {}
    for symbol, decision in decision_entries(result):
        value = decision.get("score")
        if not _is_score(value):
            value = decision.get("composite_score")
        if not _is_score(value):
            continue
        scores[str(symbol)] = float(value)
    return scores


def decision_dimension_scores(result: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Extract ``{dimension: {symbol: component score}}`` per analysis dimension.

    Reads ``component_scores`` (technical / fundamental / sentiment) emitted
    alongside the composite. A symbol missing one dimension simply does not
    vote in that dimension's cross-section — the same honest-refusal
    semantics as the composite. Runs recorded before component tracking
    (or without any usable component) return ``{}``.
    """
    vectors: dict[str, dict[str, float]] = {}
    for symbol, decision in decision_entries(result):
        components = decision.get("component_scores")
        if not isinstance(components, dict):
            continue
        for dimension, value in components.items():
            if not _is_score(value):
                continue
            vectors.setdefault(str(dimension), {})[str(symbol)] = float(value)
    return vectors


def decision_entries(result: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Normalize both stored decision shapes into ``(symbol, decision)`` pairs.

    Shared by every history-replay consumer (scores, dimensions, and the
    forecast-calibration claims extractor).
    """
    decisions = (result.get("decision") or {}).get("decisions")
    if decisions is None:
        decisions = result.get("decisions")

    entries: list[tuple[str, dict[str, Any]]] = []
    if isinstance(decisions, dict):
        pairs: Any = decisions.items()
    elif isinstance(decisions, list):
        pairs = ((d.get("symbol"), d) for d in decisions if isinstance(d, dict))
    else:
        return entries
    for symbol, decision in pairs:
        if symbol and isinstance(decision, dict):
            entries.append((str(symbol), decision))
    return entries


def information_coefficient(
    scores: dict[str, float], forward_returns: dict[str, float]
) -> float | None:
    """Spearman rank correlation between composite scores and realized returns.

    ``None`` when fewer than ``MIN_IC_SYMBOLS`` symbols have both sides, or
    when either side is rank-constant (the correlation is undefined, not
    zero) — an honest refusal rather than a fabricated number.
    """
    common = sorted(set(scores) & set(forward_returns))
    if len(common) < MIN_IC_SYMBOLS:
        return None
    signal = pd.Series([scores[s] for s in common])
    realized = pd.Series([forward_returns[s] for s in common])
    if signal.nunique() < 2 or realized.nunique() < 2:
        return None
    rho = signal.corr(realized, method="spearman")
    return None if pd.isna(rho) else round(float(rho), 6)


def ic_summary(per_run_ics: list[float]) -> dict[str, Any] | None:
    """Aggregate per-run ICs into ICIR with a t-statistic.

    ``icir = mean/std`` and ``t_stat = icir * sqrt(n)`` — the standard
    signal-quality summary (Grinold & Kahn). A single run still gets its
    mean IC; ICIR/t-stat stay ``None`` until dispersion is estimable
    (``MIN_IC_RUNS``). ``None`` only when there is nothing to aggregate.
    """
    n = len(per_run_ics)
    if n < 1:
        return None
    ics = pd.Series(per_run_ics, dtype=float)
    mean = float(ics.mean())
    std = float(ics.std(ddof=1))
    summary: dict[str, Any] = {
        "runs": n,
        "ic_mean": round(mean, 6),
        "ic_std": None if pd.isna(std) else round(std, 6),
        "ic_positive_rate": round(float((ics > 0).sum()) / n, 4),
    }
    if n >= MIN_IC_RUNS and pd.notna(std) and std > 0:
        icir = mean / std
        summary["icir"] = round(icir, 6)
        summary["t_stat"] = round(icir * (n**0.5), 4)
    else:
        summary["icir"] = None
        summary["t_stat"] = None
    return summary


def _is_score(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)
