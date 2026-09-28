"""Technical-section degraded-status pass-through.

A symbol whose quotes never arrived (empty analysis dict) or whose history
was too short (status != available) used to reach the frontend technical
card as a stack of fallback ``neutral`` rows — a missing dimension dressed
up as a real neutral verdict. The wire must say "no data" instead; healthy
entries omit the key (same convention as freshness / sparkline).
"""

from __future__ import annotations

from app.services.report_service import ReportService


def _data(analysis: dict) -> dict:
    return {
        "symbols": ["TEST"],
        "query": "TEST",
        "technical_analysis": {"TEST": analysis},
    }


def _entry(analysis: dict) -> dict:
    return ReportService.build_sections(_data(analysis))["technical_analysis"]["by_symbol"]["TEST"]


class TestTechStatusPassThrough:
    def test_no_bars_marks_entry_unavailable(self) -> None:
        entry = _entry({})

        assert entry["status"] == "unavailable"

    def test_insufficient_history_propagates_status(self) -> None:
        entry = _entry({"status": "insufficient_data", "reason": "short history", "sentiment": {}})

        assert entry["status"] == "insufficient_data"

    def test_healthy_entry_omits_status(self) -> None:
        entry = _entry({"signals": {"trend": "bullish"}, "sentiment": {"score": 40}})

        assert "status" not in entry
