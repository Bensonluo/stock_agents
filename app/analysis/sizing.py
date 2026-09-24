"""Volatility-normalized position sizing (one implementation for pipeline and ReAct).

Classic fixed-fractional ATR sizing: every position risks the same slice of
the portfolio, so a choppy stock earns a small position and a calm one a
large position. The conviction bands this replaces sized on how strong the
signal was, not on how much damage a normal day could do.
"""

from __future__ import annotations

# Portfolio fraction risked per trade; with a 2xATR stop, a losing trade
# costs at most this much of the portfolio.
RISK_BUDGET_PCT = 1.0

# Stop distance as a multiple of the daily true range (2xATR is the
# standard "beyond one wild day" stop).
STOP_MULTIPLE = 2.0

# Hard ceiling regardless of calmness — a quiet stock is not a 60% position.
POSITION_CEILING_PCT = 20.0


def atr_position_size(
    atr_pct: float | None,
    *,
    risk_budget_pct: float = RISK_BUDGET_PCT,
    stop_multiple: float = STOP_MULTIPLE,
    ceiling: float = POSITION_CEILING_PCT,
) -> float | None:
    """Position weight (% of portfolio) so each trade risks the same slice.

    weight = risk_budget / stop_distance, where stop_distance is
    stop_multiple daily true ranges. Returns None when atr_pct is missing
    or unusable — callers should fall back to their conviction bands, not
    treat "no volatility data" as "no position".
    """
    if atr_pct is None or not isinstance(atr_pct, int | float) or atr_pct <= 0:
        return None
    stop_distance_pct = stop_multiple * float(atr_pct)
    if stop_distance_pct <= 0:
        return None
    weight = risk_budget_pct / stop_distance_pct * 100.0
    return round(min(weight, ceiling), 2)
