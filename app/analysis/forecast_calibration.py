"""Forecast calibration of decision-layer confidence.

The decision agent emits a 0-1 ``confidence`` beside every action. IC
(``app.analysis.ic``) measures whether the composite *ranking* had skill;
this module measures whether ``confidence`` behaves like the probability
it is presented as: Brier score, Brier skill score against the constant
base-rate forecaster, and a reliability curve (confidence buckets vs.
empirical correctness). "80% confident" that has historically been right
55% of the time is a number worth knowing — and so is the gap.

Distinct from ``app.backtest.calibration`` (entry-signal hit rates over
price history): this scores the *probabilistic claim* the decision layer
already makes, over stored analysis history.

Pure functions only — replay/storage live in ``app.services.ic_service``.
"""

from __future__ import annotations

from typing import Any

from app.analysis.ic import decision_entries

# Number of equal-width confidence buckets in the reliability curve.
RELIABILITY_BINS = 5

# Bin edges use this epsilon so decimal boundaries (0.6 with 5 bins —
# 0.6*5 is 2.999...7 in binary) deterministically fall in the upper bin.
_BIN_EDGE_EPSILON = 1e-9


def directional_claims(result: dict[str, Any]) -> dict[str, tuple[str, float]]:
    """Extract ``{symbol: (direction, confidence)}`` from a stored result.

    Only directional actions claim anything: ``buy``-ish actions claim the
    price rises, ``sell``-ish claim it falls, ``hold`` asserts no direction
    and is not calibratable. Confidences outside [0, 1] or non-numeric
    ones are skipped — the same honest-refusal semantics as score
    extraction.
    """
    claims: dict[str, tuple[str, float]] = {}
    for symbol, decision in decision_entries(result):
        action = str(decision.get("action") or "")
        if "buy" in action:
            direction = "buy"
        elif "sell" in action:
            direction = "sell"
        else:
            continue
        confidence = decision.get("confidence")
        if not isinstance(confidence, int | float) or isinstance(confidence, bool):
            continue
        if not 0.0 <= float(confidence) <= 1.0:
            continue
        claims[str(symbol)] = (direction, float(confidence))
    return claims


def claim_correct(direction: str, forward_return: float) -> bool:
    """Whether a directional claim was vindicated by the realized return.

    Strict inequality: a flat outcome fails both directions (conservative
    — an uninformative market pays no correctness credit).
    """
    return forward_return > 0 if direction == "buy" else forward_return < 0


def brier_score(pairs: list[tuple[float, bool]]) -> float | None:
    """Mean squared error of confidence against binary outcomes.

    ``None`` only when there is nothing to score.
    """
    if not pairs:
        return None
    return round(sum((p - (1.0 if hit else 0.0)) ** 2 for p, hit in pairs) / len(pairs), 6)


def brier_skill_score(pairs: list[tuple[float, bool]]) -> float | None:
    """Brier skill score against the constant base-rate forecaster.

    ``1 - Brier / Brier_base`` where the base forecaster always predicts
    the empirical correctness rate. Zero means "no better than always
    guessing the base rate", negative means worse. ``None`` when outcomes
    are all identical (the base rate's Brier is zero — skill is
    undefined, not infinite) or when there is nothing to score.
    """
    if not pairs:
        return None
    outcomes = [1.0 if hit else 0.0 for _, hit in pairs]
    base = sum(outcomes) / len(outcomes)
    brier_base = sum((o - base) ** 2 for o in outcomes) / len(outcomes)
    if brier_base <= 0:
        return None
    brier = brier_score(pairs)
    return round(1.0 - brier / brier_base, 6)


def reliability_curve(pairs: list[tuple[float, bool]]) -> list[dict[str, Any]]:
    """Confidence buckets vs. empirical correctness (reliability diagram).

    ``RELIABILITY_BINS`` equal-width buckets over [0, 1]; empty buckets
    are omitted. Each bucket reports its sample size — a 100% rate on
    n=1 is displayed as exactly that, never hidden.
    """
    buckets: list[list[float]] = [[] for _ in range(RELIABILITY_BINS)]
    hits: list[int] = [0] * RELIABILITY_BINS
    for p, hit in pairs:
        idx = min(int(p * RELIABILITY_BINS + _BIN_EDGE_EPSILON), RELIABILITY_BINS - 1)
        buckets[idx].append(p)
        if hit:
            hits[idx] += 1

    curve: list[dict[str, Any]] = []
    for idx, confidences in enumerate(buckets):
        if not confidences:
            continue
        n = len(confidences)
        curve.append(
            {
                "bin_low": round(idx / RELIABILITY_BINS, 2),
                "bin_high": round((idx + 1) / RELIABILITY_BINS, 2),
                "n": n,
                "avg_confidence": round(sum(confidences) / n, 4),
                "empirical_rate": round(hits[idx] / n, 4),
            }
        )
    return curve
