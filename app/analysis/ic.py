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

from collections.abc import Mapping
from typing import Any

import pandas as pd

# Rank correlation on fewer than three points is numerically meaningless.
MIN_IC_SYMBOLS = 3
# ICIR needs a dispersion estimate; a single run has none.
MIN_IC_RUNS = 2

# Version stamp of the decision formula (the shared derive_recommendation
# blend + bands, plus the dimension-weights pathway). Every pipeline run
# carries it in its decision output; the IC replay that FEEDS the adaptive
# weights only counts same-vintage runs — calibrating a formula on evidence
# produced by its own predecessors would tune today's blend toward stale
# targets. Bump whenever the formula's math changes materially (weights
# logic, action bands, score normalization). Display endpoints keep the
# all-vintage view with the recorded caveat.
DECISION_FORMULA_VERSION = "2026-09-25.1"


def decision_formula_version(result: dict[str, Any]) -> str | None:
    """Read the decision formula stamp from a stored analysis result.

    Tolerates both stored shapes (pipeline ``decision.formula_version``;
    response-style top-level). Runs recorded before version stamping (and
    anything malformed) return ``None`` — legacy vintages, excluded by the
    same filter that mismatches them.
    """
    version = (result.get("decision") or {}).get("formula_version")
    if version is None:
        version = result.get("formula_version")
    return version if isinstance(version, str) and version else None


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


# ---------------------------------------------------------------------------
# IC-driven dimension weighting: closing the loop the IC arc opened. The
# measured predictive power of each dimension feeds back into the composite
# recommendation blend — Grinold & Kahn's factor-weighting logic applied to
# our own decision layer.
# ---------------------------------------------------------------------------

# The directional blend derive_recommendation uses when no measured evidence
# applies (risk's 0.10 modifier weight lives elsewhere and never adapts —
# risk is a modifier, not a signal, and no IC is measured for it).
STATIC_DIMENSION_WEIGHTS: dict[str, float] = {
    "fundamental": 0.45,
    "technical": 0.30,
    "sentiment": 0.15,
}

# A dimension votes on weighting only with a dispersion-estimated IC backed
# by at least this many evaluated runs. Below it the whole blend stays
# static: renormalization couples dimensions, so adapting on partial
# evidence would silently redistribute weight among unequally-measured dims.
MIN_ADAPT_RUNS = 12
# Shrinkage intensity λ = n/(n+k) toward the measured-IC targets: the
# weakest dimension's run count governs. n=12 → λ=1/3, n=36 → 0.6.
ADAPT_SHRINK_K = 24
# Share bounds (within the directional mass) so no dimension is fully
# silenced nor allowed to dominate, however strong its measured IC.
WEIGHT_FLOOR = 0.05
WEIGHT_CAP = 0.60


def adaptive_dimension_weights(
    ic_by_dimension: Mapping[str, dict[str, Any] | None],
    *,
    static_weights: Mapping[str, float] | None = None,
    min_runs: int = MIN_ADAPT_RUNS,
    shrink_k: int = ADAPT_SHRINK_K,
    floor: float = WEIGHT_FLOOR,
    cap: float = WEIGHT_CAP,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Blend static dimension weights toward measured-IC targets.

    Args:
        ic_by_dimension: ``{dimension: ic_summary(...) | None}`` — the
            per-dimension summaries ``evaluate_decision_ic`` already emits.
        static_weights: prior blend to shrink toward (defaults to the live
            45/30/15 constants).

    Returns:
        ``(weights, provenance)``. Weights are the directional blend only
        (same support and total mass as ``static_weights``); provenance
        records mode, gate decision, shrinkage and per-dimension evidence
        so the decision output can carry its own audit trail.

    Gate: every directional dimension must have a qualified summary
    (``runs >= min_runs`` and an IC dispersion estimate). Any shortfall
    keeps the static blend — an honest refusal, not a partial tilt. All
    measured ICs non-positive also refuses: re-weighting cannot rescue a
    composite with no predictive dimension, and sign-flipping scores would
    be a far larger behavioral change than re-weighting.
    """
    prior = dict(static_weights or STATIC_DIMENSION_WEIGHTS)
    mass = sum(prior.values())
    evidence: dict[str, Any] = {}
    for dim in prior:
        summary = ic_by_dimension.get(dim)
        if summary is None:
            evidence[dim] = {"qualified": False, "reason": "no summary"}
        elif summary.get("ic_std") is None:
            evidence[dim] = {"qualified": False, "reason": "no dispersion estimate"}
        elif int(summary.get("runs", 0)) < min_runs:
            evidence[dim] = {
                "qualified": False,
                "reason": f"{summary.get('runs', 0)} runs < {min_runs}",
            }
        else:
            evidence[dim] = {
                "qualified": True,
                "runs": int(summary["runs"]),
                "ic_mean": summary["ic_mean"],
                "ic_positive_rate": summary.get("ic_positive_rate"),
            }

    unqualified = [d for d, e in evidence.items() if not e["qualified"]]
    if unqualified:
        reason = "; ".join(f"{d}: {evidence[d]['reason']}" for d in unqualified)
        return dict(prior), _weight_provenance(prior, evidence, mode="static", reason=reason)

    positive = {d: max(float(e["ic_mean"]), 0.0) for d, e in evidence.items()}
    if sum(positive.values()) <= 0:
        return dict(prior), _weight_provenance(
            prior, evidence, mode="static", reason="no dimension shows positive measured IC"
        )

    # Shrinkage toward the IC targets, governed by the weakest dimension.
    n_min = min(int(e["runs"]) for e in evidence.values())
    lam = n_min / (n_min + shrink_k)

    target_total = sum(positive.values())
    blended: dict[str, float] = {}
    for dim in prior:
        static_share = prior[dim] / mass
        target_share = positive[dim] / target_total
        blended[dim] = (1.0 - lam) * static_share + lam * target_share

    # Bounded distortion regardless of how skewed the ICs are: the blend is
    # projected onto {sum = 1, floor <= share <= cap} — a true box-simplex
    # projection, so the cap holds in the FINAL weights. A naive
    # clip-then-renormalize would push the capped dimension back above the
    # cap when the renormalization restores the trimmed mass.
    projected = _project_to_box(blended, floor, cap)
    weights = {d: round(projected[d] * mass, 6) for d in prior}

    provenance = _weight_provenance(
        prior,
        evidence,
        mode="adaptive",
        weights=weights,
        lam=lam,
        n_min=n_min,
        targets={d: positive[d] / target_total for d in prior},
    )
    return weights, provenance


def _project_to_box(shares: Mapping[str, float], floor: float, cap: float) -> dict[str, float]:
    """Project onto {sum = 1, floor <= share <= cap} — box-simplex water-filling.

    Each round renormalizes the free dimensions over the mass the pinned
    ones leave, then pins the single most-violated dimension at its bound.
    One pin per round (not all violators at once) keeps the pinned mass
    feasible — pinning two floors and one cap simultaneously can overshoot
    mass 1. The optimal projection has at most n-1 active bounds, so the
    loop terminates with the invariant intact.
    """
    current = {d: s / sum(shares.values()) for d, s in shares.items()}
    pinned: dict[str, float] = {}
    while len(pinned) < len(current) - 1:
        free = [d for d in current if d not in pinned]
        free_sum = sum(current[d] for d in free)
        free_mass = 1.0 - sum(pinned.values())
        if not free or free_sum <= 0 or free_mass <= 0:
            break
        for d in free:
            current[d] = current[d] / free_sum * free_mass
        worst, worst_bound, worst_gap = None, None, -1.0
        for d in free:
            if current[d] < floor and floor - current[d] > worst_gap:
                worst, worst_bound, worst_gap = d, floor, floor - current[d]
            elif current[d] > cap and current[d] - cap > worst_gap:
                worst, worst_bound, worst_gap = d, cap, current[d] - cap
        if worst is None:
            break
        current[worst] = worst_bound
        pinned[worst] = worst_bound
    return current


def _weight_provenance(
    static_weights: Mapping[str, float],
    evidence: Mapping[str, Any],
    *,
    mode: str,
    reason: str | None = None,
    weights: Mapping[str, float] | None = None,
    lam: float | None = None,
    n_min: int | None = None,
    targets: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    return {
        "mode": mode,
        "reason": reason,
        "static_weights": dict(static_weights),
        "weights": dict(weights or static_weights),
        "lambda": round(lam, 4) if lam is not None else None,
        "runs_weakest_dimension": n_min,
        "targets": {d: round(t, 4) for d, t in targets.items()} if targets else None,
        "per_dimension": dict(evidence),
    }
