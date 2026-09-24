"""Portfolio construction helper — the deterministic allocation layer.

Lights up the risk engine's ``concentration_hhi`` (extracted with the engine
but never consumed) with a conviction-tilted inverse-volatility allocation:
weights ∝ conviction / volatility with a per-symbol cap. Full mean-variance
optimization is deliberately avoided — with ~250 daily observations the
covariance estimate is mostly noise (Michaud's "estimation error maximizer"
critique); inverse-vol is the robust default for research tooling.
"""

from __future__ import annotations

from typing import Any

from app.analysis.risk import concentration_hhi

DEFAULT_MAX_WEIGHT = 0.20


def suggest_weights(
    candidates: dict[str, dict[str, float | None]],
    *,
    max_weight: float = DEFAULT_MAX_WEIGHT,
) -> dict[str, Any] | None:
    """Conviction-tilted inverse-volatility weights with a per-symbol cap.

    ``candidates`` maps symbol -> ``{"conviction": 0..1, "volatility_annualized":
    > 0}`` (either may be None/missing — the symbol is then excluded and
    noted). Fewer than two eligible symbols yield None: a single-name
    "allocation" is position sizing, not portfolio construction.

    Capped excess is redistributed proportionally among the uncapped symbols,
    iteratively — capping one symbol changes the others' shares. Once every
    symbol is capped the remainder lands in ``cash_reserve``; weights always
    sum to ≤ 1.
    """
    eligible: dict[str, float] = {}
    excluded: list[str] = []
    for symbol, fields in candidates.items():
        conviction = fields.get("conviction")
        vol = fields.get("volatility_annualized")
        usable_conviction = isinstance(conviction, int | float) and conviction > 0
        usable_vol = isinstance(vol, int | float) and vol > 0
        if not (usable_conviction and usable_vol):
            excluded.append(symbol)
            continue
        eligible[symbol] = float(conviction) / float(vol)

    if len(eligible) < 2:
        return None

    raw_total = sum(eligible.values())
    weights = {symbol: value / raw_total for symbol, value in eligible.items()}
    capped: set[str] = set()
    for _ in range(len(eligible)):
        overflow = [s for s, w in weights.items() if s not in capped and w > max_weight + 1e-12]
        if not overflow:
            break
        capped.update(overflow)
        for symbol in overflow:
            weights[symbol] = max_weight
        rest = {s: w for s, w in weights.items() if s not in capped}
        rest_total = sum(rest.values())
        if rest_total <= 0:
            break
        free_budget = 1.0 - max_weight * len(capped)
        for symbol, weight in rest.items():
            weights[symbol] = free_budget * weight / rest_total

    cash_reserve = max(0.0, 1.0 - sum(weights.values()))
    return {
        "method": "conviction_tilted_inverse_volatility",
        "weights": {
            symbol: round(weight, 6)
            for symbol, weight in sorted(weights.items(), key=lambda item: -item[1])
        },
        "cash_reserve": round(cash_reserve, 6),
        "excluded": excluded,
        "concentration_hhi": concentration_hhi(weights),
        "max_weight": max_weight,
    }
