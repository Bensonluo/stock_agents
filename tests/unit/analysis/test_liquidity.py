"""ADV liquidity annotation: exact turnover preferred, per-market floors.

Exit liquidity is a risk axis the score never covered: ADV is computable
from data the fetchers already collect (volume / 成交额) yet nothing consumed
it. These tests pin the engine helper (exact turnover series preferred over
close×volume, which the 手-denominated CN volume column would understate by
100x) and the assess_symbol annotation block (per-currency floors, thin
warning) — the risk score itself stays untouched.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from app.analysis.risk import average_dollar_volume
from app.config import get_settings
from app.tools.risk.assessment import assess_symbol


def _bars(closes, volumes=None, amount=None) -> dict:
    bars = {
        "dates": [(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(len(closes))],
        "close": list(closes),
    }
    if volumes is not None:
        bars["volume"] = list(volumes)
    if amount is not None:
        bars["amount"] = list(amount)
    return bars


def test_exact_turnover_series_wins_over_close_times_volume() -> None:
    # CN bars: volume in 手, so close×volume would be 10; the amount series
    # (yuan) is the only correct reading.
    bars = _bars([10.0] * 25, volumes=[1] * 25, amount=[30_000_000] * 25)

    assert average_dollar_volume(bars) == 30_000_000.0


def test_close_times_volume_fallback_for_share_denominated_bars() -> None:
    bars = _bars([10.0] * 25, volumes=[1_000_000] * 25)

    assert average_dollar_volume(bars) == 10_000_000.0  # 10 x 1M shares


def test_window_averages_only_the_trailing_bars() -> None:
    bars = _bars([10.0] * 30, amount=[1.0] * 10 + [3.0] * 20)

    assert average_dollar_volume(bars) == 3.0  # the ten 1.0 bars are outside


def test_min_observations_guard() -> None:
    assert average_dollar_volume(_bars([10.0] * 4, volumes=[100.0] * 4)) is None


def test_non_finite_and_non_positive_values_are_not_observations() -> None:
    bars = _bars(
        [10.0] * 25,
        amount=[float("nan")] * 5 + [0.0] * 5 + [10.0] * 20,
    )

    assert average_dollar_volume(bars) == 10.0


def test_no_volume_or_amount_data_returns_none() -> None:
    assert average_dollar_volume(_bars([10.0] * 25)) is None


def test_assess_symbol_usd_floor_flags_thin_and_warns() -> None:
    floor = get_settings().min_adv_usd
    thin_volume = floor / 100.0 / 4.0  # close 100 -> ADV = floor / 4

    result = assess_symbol(
        "TEST",
        {"symbol": "TEST", "historical_data": _bars([100.0] * 25, volumes=[thin_volume] * 25)},
    )

    liquidity = result["liquidity"]
    assert liquidity["level"] == "thin"
    assert liquidity["currency"] == "USD"
    assert liquidity["min_adv"] == floor
    assert liquidity["status"] == "available"
    assert any("turnover" in warning for warning in result["warnings"])


def test_assess_symbol_cny_floor_reads_amount_series() -> None:
    floor = get_settings().min_adv_cny
    # volume=1 (手) would read as ~10 yuan/day — only the exact turnover
    # series can clear a CNY floor of this size.
    result = assess_symbol(
        "600000",
        {
            "symbol": "600000",
            "historical_data": _bars([10.0] * 25, volumes=[1] * 25, amount=[floor * 2] * 25),
        },
    )

    liquidity = result["liquidity"]
    assert liquidity["level"] == "adequate"
    assert liquidity["currency"] == "CNY"
    assert liquidity["min_adv"] == floor
    assert not any("turnover" in warning for warning in result["warnings"])


def test_missing_volume_degrades_to_insufficient_data_annotation() -> None:
    result = assess_symbol("TEST", {"symbol": "TEST", "historical_data": _bars([100.0] * 25)})

    liquidity = result["liquidity"]
    assert liquidity["adv_20d"] is None
    assert liquidity["level"] is None
    assert liquidity["status"] == "insufficient_data"
    assert not any("turnover" in warning for warning in result["warnings"])


def test_liquidity_is_annotation_only_risk_score_keys_unchanged() -> None:
    floor = get_settings().min_adv_usd
    thin_volume = floor / 100.0 / 4.0
    thin = assess_symbol(
        "TEST",
        {"symbol": "TEST", "historical_data": _bars([100.0] * 25, volumes=[thin_volume] * 25)},
    )
    liquid = assess_symbol(
        "TEST",
        {
            "symbol": "TEST",
            "historical_data": _bars([100.0] * 25, volumes=[floor / 100.0 * 4] * 25),
        },
    )

    # Exit liquidity is reported beside the score, never folded into it —
    # identical price risk must produce an identical score.
    assert thin["risk_score"] == liquid["risk_score"]
    assert thin["risk_level"] == liquid["risk_level"]
    assert np.isclose(thin["metrics"]["volatility"], liquid["metrics"]["volatility"])
