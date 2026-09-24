"""Market-regime classification from the benchmark series.

Per-symbol analysis is regime-blind: the same technical picture means
different things in a grinding bull market and a high-volatility bear.
The benchmark series the data layer already fetches (``^GSPC`` /
``000001.SS``) carries the answer — this module reads it and classifies
the market the analyzed names actually live in.

Pure annotation, in the liquidity / sector_relative tradition: the
regime block describes context and never touches risk scores, weights,
or position sizes. Policy decisions built on it are separate, explicit
changes.

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
