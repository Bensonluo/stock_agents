"""Regime-trend extraction from stored analysis results.

The regime-conditional IC view bins replayed runs by the market regime they
were made in. The regime block lives at ``risk_assessment.market_regime`` in
both stored shapes — the pipeline nests it beside ``risk_by_symbol`` (attached
at the risk-state level since iteration 76), and the ReAct path parks it as a
namespaced key beside the flat per-symbol entries (iteration 115). Runs whose
regime was never measured — recorded before regime tracking, degraded
benchmarks, or a withheld trend on a sub-200-bar benchmark — must bin apart
from measured regimes, never as a fake neutral.
"""

from __future__ import annotations

from app.analysis.ic import regime_trend_of_result

_BULL = {"status": "ok", "bars": 300, "trend": "bull", "price_vs_sma200": 0.064}
_BEAR = {"status": "ok", "bars": 300, "trend": "bear", "price_vs_sma200": -0.084}


class TestRegimeTrendExtraction:
    def test_pipeline_nested_shape_reads_trend(self) -> None:
        result = {"risk_assessment": {"risk_by_symbol": {"AAA": {}}, "market_regime": _BULL}}

        assert regime_trend_of_result(result) == "bull"

    def test_react_flat_shape_reads_trend(self) -> None:
        result = {"risk_assessment": {"AAA": {"risk_level": "medium"}, "market_regime": _BEAR}}

        assert regime_trend_of_result(result) == "bear"

    def test_neutral_trend_is_a_measured_bin(self) -> None:
        result = {"risk_assessment": {"market_regime": {**_BULL, "trend": "neutral"}}}

        assert regime_trend_of_result(result) == "neutral"

    def test_withheld_trend_bins_apart_from_measured_regimes(self) -> None:
        # Sub-200-bar benchmark: the classifier emits status ok but withholds
        # the trend — that run is NOT a measured neutral.
        result = {
            "risk_assessment": {"market_regime": {"status": "ok", "bars": 150, "trend": None}}
        }

        assert regime_trend_of_result(result) is None

    def test_degraded_or_missing_regimes_return_none(self) -> None:
        assert regime_trend_of_result({"risk_assessment": {}}) is None
        assert regime_trend_of_result({}) is None
        insufficient = {"risk_assessment": {"market_regime": {"status": "insufficient_history"}}}
        assert regime_trend_of_result(insufficient) is None
        non_dict = {"risk_assessment": {"market_regime": "bull"}}
        assert regime_trend_of_result(non_dict) is None
