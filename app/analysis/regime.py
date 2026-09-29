"""Market-regime classification and the warnings it conditions.

Per-symbol analysis is regime-blind: the same technical picture means
different things in a grinding bull market and a high-volatility bear.
The benchmark series the data layer already fetches (``^GSPC`` /
``000001.SS``) carries the answer — this module reads it and classifies
the market the analyzed names actually live in.

Pure annotation, in the liquidity / sector_relative tradition: the
regime block describes context and never touches risk scores, weights,
or position sizes. Policy decisions built on it are separate, explicit
changes.

The ``decision_warnings`` / ``regime_warnings`` /
``option_regime_warnings`` / ``option_context_line`` generators live
here so both decision surfaces — the pipeline decision agent and the
ReAct derived recommendations — import the SAME functions from a leaf
module (the report service cannot import the decision agent: circular).

Pure functions only — no network, no storage.
"""

from __future__ import annotations

from typing import Any

# Trend: close vs its 200-bar simple mean, with a dead-band so "barely
# above the average" is not narrated as a bull market.
SMA_WINDOW = 200
TREND_BAND = 0.02  # ±2% around the SMA is "neutral"

# Volatility: 20-bar realized vol vs the full-window realized vol.
VOL_WINDOW = 20
MIN_BARS = 60  # shorter benchmarks cannot support even a coarse ratio
VOL_ELEVATED = 1.3
VOL_CALM = 0.7

DRAWDOWN_WINDOW = 252  # 52 weeks, truncated to available bars


def classify_market_regime(closes: list[float]) -> dict[str, Any] | None:
    """Classify the market behind a benchmark close series.

    Trend comes from the close vs its SMA-200 (±2% dead-band); the
    volatility regime from the ratio of recent (20-bar) to full-window
    realized volatility; drawdown from the 52w high is reported as
    context. ``None`` when the series is too short to say anything —
    an honest refusal rather than a guessed regime.
    """
    prices = [c for c in closes if isinstance(c, int | float) and c > 0]
    if len(prices) < MIN_BARS:
        return None

    last = prices[-1]

    # --- Trend: close vs SMA-200 (needs the full window; otherwise
    # trend is withheld, not approximated on a shorter mean).
    trend: str | None = None
    price_vs_sma: float | None = None
    if len(prices) >= SMA_WINDOW:
        sma = sum(prices[-SMA_WINDOW:]) / SMA_WINDOW
        price_vs_sma = last / sma - 1
        if price_vs_sma > TREND_BAND:
            trend = "bull"
        elif price_vs_sma < -TREND_BAND:
            trend = "bear"
        else:
            trend = "neutral"

    # --- Volatility regime: recent realized vol vs the full window's.
    vol_20 = _realized_vol(prices[-VOL_WINDOW:])
    vol_full = _realized_vol(prices)
    vol_ratio: float | None = None
    volatility_regime: str | None = None
    if vol_20 is not None and vol_full is not None and vol_full > 0:
        vol_ratio = vol_20 / vol_full
        if vol_ratio >= VOL_ELEVATED:
            volatility_regime = "elevated"
        elif vol_ratio <= VOL_CALM:
            volatility_regime = "calm"
        else:
            volatility_regime = "normal"

    if trend is None and volatility_regime is None:
        return None

    # --- Context: drawdown from the 52w (or available) high.
    window = prices[-DRAWDOWN_WINDOW:]
    drawdown = last / max(window) - 1

    regime: dict[str, Any] = {
        "status": "ok",
        "bars": len(prices),
        "trend": trend,
        "volatility_regime": volatility_regime,
        "drawdown_from_52w_high": round(drawdown, 4),
    }
    if price_vs_sma is not None:
        regime["price_vs_sma200"] = round(price_vs_sma, 4)
    if vol_ratio is not None:
        regime["vol_ratio_20d_vs_full"] = round(vol_ratio, 4)
    return regime


def _realized_vol(prices: list[float]) -> float | None:
    """Annualized realized volatility of a close series (sqrt(252) convention).

    ``None`` when there are not at least two usable returns — volatility
    of a single return is not a measurement.
    """
    if len(prices) < 3:
        return None
    returns = [prices[i] / prices[i - 1] - 1 for i in range(1, len(prices)) if prices[i - 1] > 0]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return (var * 252) ** 0.5


def decision_warnings(action: str, risk: dict, confidence: float) -> list[str]:
    """Decision-specific warnings for a recommendation.

    Low confidence (< 0.5 on the formula's 0-1 scale — degraded holds and
    stale-capped calls), high-risk buys, and strong-conviction actions.
    Shared by the pipeline decision agent and the ReAct derived
    recommendations so both paths speak with one voice.
    """
    warnings: list[str] = []

    if confidence < 0.5:
        warnings.append(
            "Low confidence in this recommendation. Consider waiting for clearer signals."
        )

    risk_level = risk.get("risk_level", "")
    if risk_level in ["high", "very_high"]:
        if "buy" in action:
            warnings.append("High risk stock - use strict stop-loss and limit position size.")

    if "strong" in action:
        warnings.append("Strong conviction signal - ensure it aligns with your risk tolerance.")

    return warnings


def regime_warnings(action: str, regime: dict | None) -> list[str]:
    """Buy-side risk warnings from the market regime (iteration 76 block).

    Pure annotation, in the liquidity / sector_relative tradition: the
    regime can only APPEND warning strings — never an input to the
    action, score, confidence, or position size (all decided before
    this runs). Sells/holds get nothing: the regime's edge case is a
    recommendation to add risk into a hostile market.
    """
    if not isinstance(regime, dict) or regime.get("status") != "ok" or "buy" not in action:
        return []

    warnings: list[str] = []
    if regime.get("trend") == "bear":
        vs_sma = regime.get("price_vs_sma200")
        where = (
            f" ({vs_sma:+.1%} vs its 200-day average)" if isinstance(vs_sma, int | float) else ""
        )
        warnings.append(
            "Counter-trend entry: the benchmark is in a bear regime"
            f"{where} — counter-trend buys historically carry lower hit rates."
        )
    if regime.get("volatility_regime") == "elevated":
        ratio = regime.get("vol_ratio_20d_vs_full")
        scale = f" ({ratio:.1f}x its full-window level)" if isinstance(ratio, int | float) else ""
        warnings.append(
            f"Market volatility is elevated{scale} — expect wider swings and size accordingly."
        )
    drawdown = regime.get("drawdown_from_52w_high")
    if isinstance(drawdown, int | float) and drawdown <= -0.20:
        warnings.append(
            f"Benchmark sits {abs(drawdown):.1%} below its 52-week high — "
            "falling-knife risk; prefer scaling in over a single entry."
        )
    return warnings


_OPTION_REGIME_WORDS = {"恐慌": "panic", "自满": "complacency", "中性": "a neutral state"}


def option_regime_warnings(action: str, option_implied: dict | None) -> list[str]:
    """Buy-side risk warnings from the option-implied regime (iteration 155 block).

    Same annotation-only contract as regime_warnings: appends strings, never
    an input to the action, score, confidence, or position size. Sells/holds
    get nothing — the edge case is adding risk when options price the tail
    cheaply (自满) or while realized panic is destabilizing fills (恐慌).
    """
    if (
        not isinstance(option_implied, dict)
        or option_implied.get("status") != "ok"
        or "buy" not in action
    ):
        return []
    qvix = option_implied.get("qvix")
    pct = qvix.get("percentile_1y") if isinstance(qvix, dict) else None
    where = f" (QVIX at the {pct:.0%} 1-year percentile)" if isinstance(pct, int | float) else ""
    regime = option_implied.get("regime")
    if regime == "恐慌":
        return [
            f"Options market is pricing panic{where} — entries during panic face "
            "wide swings and unstable fills; prefer scaling in over a single entry."
        ]
    if regime == "自满":
        return [
            f"Options market is complacent{where} — downside insurance is cheap and "
            "tail risk may be underpriced; a volatility repricing can hit new entries."
        ]
    return []


def option_context_line(option_implied: dict | None) -> str | None:
    """One-line option-implied context for the synthesis prompt; None when unknown.

    Narrative context for the LLM only (mirrors _market_context_line's
    contract): never an input to any score, weight, or position size.
    """
    if not isinstance(option_implied, dict) or option_implied.get("status") != "ok":
        return None
    qvix = option_implied.get("qvix")
    current = qvix.get("current") if isinstance(qvix, dict) else None
    label = _OPTION_REGIME_WORDS.get(option_implied.get("regime"))
    if not isinstance(current, int | float) or label is None:
        return None
    pct = qvix.get("percentile_1y") if isinstance(qvix, dict) else None
    detail = f" at the {pct:.0%} 1-year percentile" if isinstance(pct, int | float) else ""
    return f"the options market implies {label} (QVIX {current}{detail})"
