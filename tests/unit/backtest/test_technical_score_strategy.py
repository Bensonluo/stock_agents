"""Parity tests for the ``technical_score`` strategy.

The strategy's whole value is being a faithful replay of the live decision
layer's technical dimension score (``daily.calculate_sentiment`` composed
with ``generate_signals``/``calculate_indicators``). These tests pin that
equivalence bar-by-bar against the live pipeline itself — the live side is
recomputed on the truncated frame ``df[: t+1]`` exactly as it would have run
on that date, so exact equality means the backtest fills correspond to the
scores the live agent would actually have emitted.

The one accepted divergence class is measure-zero band-edge rounding: the
live pipeline rounds RSI to 4dp and SMA/MACD to 6dp before threshold
comparisons, so a value landing within ~5e-5 of a band boundary can label
differently. Synthetic tapes make those coincidences ~impossible; fixed
seeds keep the suite deterministic.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analysis.technical.daily import (
    calculate_indicators,
    calculate_sentiment,
    generate_signals,
)
from app.backtest.engine import (
    DEFAULT_PARAMS,
    STRATEGIES,
    STRATEGY_PARAMETERS,
    _target_position,
    _technical_score_series,
    run_backtest,
)
from tests.unit.backtest.test_engine import ZERO, _ohlc


def _tape(n: int = 300, *, drift: float = 0.0004, seed: int = 7):
    """Deterministic random-walk OHLCV with volume spikes.

    Returns two views of the same tape: engine casing (capitalized columns)
    and live casing (lowercase, what ``calculate_indicators`` reads). Volume
    is lognormal with ~8% of bars spiked ×8 so the ratio>2 confirmation
    branch is exercised, not just the quiet path.
    """
    rng = np.random.default_rng(seed)
    ret = rng.normal(drift, 0.015, n)
    close = 100.0 * np.cumprod(1.0 + ret)
    open_ = np.concatenate([[close[0]], close[:-1]])  # gap-free
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.004, n)))
    volume = 1e6 * np.exp(rng.normal(0, 0.3, n)) * np.where(rng.random(n) < 0.08, 8.0, 1.0)
    index = pd.bdate_range("2023-01-02", periods=n)
    cap = pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=index,
    )
    live = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )
    return cap, live


def _live_score(live_frame: pd.DataFrame) -> float:
    """Score the live pipeline produces on the final bar of ``live_frame``."""
    indicators = calculate_indicators(live_frame)
    signals = generate_signals(live_frame, indicators)
    return calculate_sentiment(signals, indicators)["score"]


class TestLiveParity:
    @pytest.mark.parametrize("t", [60, 100, 150, 299])
    def test_replayed_score_equals_live_pipeline(self, t: int) -> None:
        cap, live = _tape()
        replayed = _technical_score_series(cap)
        assert replayed.iloc[t] == _live_score(live.iloc[: t + 1])

    def test_parity_holds_on_a_falling_tape(self) -> None:
        # Bearish contributions (−30 trend, −20 RSI, −15 Bollinger, −15
        # volume) only fire on a declining tape — parity must hold there too.
        cap, live = _tape(drift=-0.002, seed=11)
        replayed = _technical_score_series(cap)
        for t in (60, 120, 200, cap.index.size - 1):
            assert replayed.iloc[t] == _live_score(live.iloc[: t + 1])

    def test_no_look_ahead_truncation_invariance(self) -> None:
        # The score at bar t must not depend on bars after t: appending
        # future data cannot rewrite history. This is the property that
        # makes the replay point-in-time honest.
        cap, _ = _tape()
        full = _technical_score_series(cap)
        truncated = _technical_score_series(cap.iloc[:150])
        np.testing.assert_allclose(
            full.iloc[:150].to_numpy(), truncated.to_numpy(), rtol=0, atol=1e-12
        )

    def test_warmup_bars_carry_only_the_macd_vote(self) -> None:
        # Before RSI's first value (bar 14) and the SMA windows, the only
        # contributor is MACD's always-firing ±20 — matching the live
        # pipeline where unavailable indicators simply abstain.
        cap, _ = _tape()
        score = _technical_score_series(cap)
        # Bar 0: macd_line == signal_line == close[0] → hist == 0 → the
        # live `elif macd:` branch scores bearish.
        assert score.iloc[0] == -20.0
        assert set(score.iloc[:14].unique()).issubset({-20.0, 20.0})


class TestThresholdRule:
    def test_target_is_score_above_threshold(self) -> None:
        cap, _ = _tape()
        target = _target_position(cap, "technical_score", {"score_threshold": 10.0})
        score = _technical_score_series(cap)
        pd.testing.assert_series_equal(target, (score >= 10.0).astype(float))

    def test_registration_and_defaults(self) -> None:
        assert "technical_score" in STRATEGIES
        assert STRATEGY_PARAMETERS["technical_score"] == frozenset({"score_threshold"})
        # 10 = the live pipeline's moderate_buy floor.
        assert DEFAULT_PARAMS["technical_score"] == {"score_threshold": 10}

    def test_unknown_parameter_rejected(self) -> None:
        cap, _ = _tape()
        with pytest.raises(ValueError, match="Unknown parameter"):
            run_backtest(cap, strategy="technical_score", score_thresholds=10)


class TestRunBacktest:
    def test_smoke_deterministic_with_default_threshold(self) -> None:
        cap, _ = _tape(seed=3)
        first = run_backtest(cap, strategy="technical_score", cost_model=ZERO)
        second = run_backtest(cap, strategy="technical_score", cost_model=ZERO)

        assert first.params["score_threshold"] == 10  # default applied
        assert first.metrics["total_return"] is not None
        assert first.equity.iloc[-1] == second.equity.iloc[-1]
        assert first.metrics == second.metrics

        # The tape produces both in and out of the market…
        score = _technical_score_series(cap)
        assert (score >= 10).any() and not (score >= 10).all()
        # …so at least one fill happened.
        assert len(first.trades) >= 1

    def test_unreachable_threshold_stays_flat(self) -> None:
        cap, _ = _tape(seed=5)
        score = _technical_score_series(cap)
        result = run_backtest(
            cap,
            strategy="technical_score",
            cost_model=ZERO,
            score_threshold=float(score.max()) + 1.0,
        )
        assert result.trades == []
        assert result.equity.iloc[-1] == pytest.approx(10_000.0)

    def test_matches_engine_ohlcv_contract(self) -> None:
        # The legacy _ohlc helper (flat volume, gap-free) is also a valid
        # tape for the replay — guards against column-shape assumptions.
        result = run_backtest(_ohlc(200, drift=0.003), strategy="technical_score")
        assert result.metrics["total_return"] is not None
