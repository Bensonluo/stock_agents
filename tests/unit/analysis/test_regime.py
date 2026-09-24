"""Market-regime classification math (pure, deterministic)."""

from __future__ import annotations

import math

from app.analysis.regime import classify_market_regime


def _tape(n: int, start: float, daily: float) -> list[float]:
    """Deterministic close tape growing/falling at ``daily`` per bar."""
    return [round(start * ((1 + daily) ** i), 6) for i in range(n)]


def _flat_with_noise(n: int, base: float) -> list[float]:
    """Flat tape with a tiny deterministic wiggle (vol but no trend)."""
    return [round(base * (1 + 0.001 * math.sin(i)), 6) for i in range(n)]


class TestClassifyMarketRegime:
    def test_steady_uptrend_is_bull(self) -> None:
        closes = _tape(300, 100.0, 0.002)  # ~+2%/10bars compounding
        regime = classify_market_regime(closes)
        assert regime is not None
        assert regime["trend"] == "bull"
        assert regime["price_vs_sma200"] > 0.02
        assert regime["status"] == "ok"

    def test_steady_downtrend_is_bear(self) -> None:
        closes = _tape(300, 100.0, -0.002)
        regime = classify_market_regime(closes)
        assert regime is not None
        assert regime["trend"] == "bear"
        assert regime["price_vs_sma200"] < -0.02

    def test_flat_tape_is_neutral(self) -> None:
        regime = classify_market_regime(_flat_with_noise(300, 100.0))
        assert regime is not None
        assert regime["trend"] == "neutral"
        assert abs(regime["price_vs_sma200"]) <= 0.02

    def test_vol_ratio_bands(self) -> None:
        # Calm recent past on a noisy tape: 260 wiggling bars then 40 flat.
        noisy = [round(100 * (1 + 0.01 * math.sin(i)), 6) for i in range(260)]
        calm = [round(100 * (1 + 0.0005 * math.sin(i)), 6) for i in range(40)]
        regime = classify_market_regime(noisy + calm)
        assert regime is not None
        assert regime["volatility_regime"] == "calm"
        assert regime["vol_ratio_20d_vs_full"] < 0.7

        # Elevated: calm history then a violent tail.
        violent = [round(100 * (1 + 0.05 * math.sin(i)), 6) for i in range(40)]
        regime = classify_market_regime(noisy[:240] + violent)
        assert regime is not None
        assert regime["volatility_regime"] == "elevated"
        assert regime["vol_ratio_20d_vs_full"] > 1.3

    def test_drawdown_from_52w_high(self) -> None:
        rises = _tape(260, 100.0, 0.001)  # peak ~130 near the end
        falls = _tape(40, rises[-1], -0.005)  # ~-18% off the high
        regime = classify_market_regime(rises + falls)
        assert regime is not None
        assert regime["drawdown_from_52w_high"] < -0.15

    def test_short_series_refused(self) -> None:
        assert classify_market_regime(_tape(59, 100.0, 0.01)) is None
        assert classify_market_regime([]) is None

    def test_sub_sma_window_withholds_trend_keeps_vol(self) -> None:
        # 100 bars: enough for the vol ratio, not for SMA-200 — trend is
        # withheld rather than approximated on a shorter mean.
        regime = classify_market_regime(_flat_with_noise(100, 100.0))
        assert regime is not None
        assert regime["trend"] is None
        assert "price_vs_sma200" not in regime
        assert regime["volatility_regime"] is not None

    def test_non_positive_prices_filtered(self) -> None:
        closes = _tape(300, 100.0, 0.001)
        closes[150] = 0.0  # one corrupt bar
        closes[151] = -5.0
        regime = classify_market_regime(closes)
        assert regime is not None
        assert regime["bars"] == 298
