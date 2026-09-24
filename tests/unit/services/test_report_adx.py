"""Technical-section trend-quality pass-through.

The daily engine now grades each trend verdict with Wilder's ADX
(``indicators.adx`` + ``signals.trend_strength``); these tests pin the
report wire: both keys reach the technical card when the engine measured
them and stay absent on degraded entries — the same convention as
freshness and the sparkline.
"""

from __future__ import annotations

from app.services.report_service import ReportService


def _data(indicators: dict | None, signals_extra: dict | None = None) -> dict:
    analysis: dict = {"signals": {"trend": "bullish"}, "sentiment": {}}
    if indicators is not None:
        analysis["indicators"] = indicators
    if signals_extra:
        analysis["signals"] = {**analysis["signals"], **signals_extra}
    return {
        "symbols": ["TEST"],
        "query": "TEST adx",
        "technical_analysis": {"TEST": analysis},
    }


def _entry(data: dict) -> dict:
    return ReportService.build_sections(data)["technical_analysis"]["by_symbol"]["TEST"]


class TestAdxPassThrough:
    def test_adx_and_strength_reach_the_card(self) -> None:
        entry = _entry(_data({"adx": 27.4}, {"trend_strength": "strong"}))

        assert entry["adx"] == 27.4
        assert entry["trend_strength"] == "strong"

    def test_short_history_leaves_both_keys_absent(self) -> None:
        entry = _entry(_data(None))

        assert "adx" not in entry
        assert "trend_strength" not in entry
