"""Decision-warning pass-through to the recommendations wire.

The decision agent attaches warnings to every decision (low-confidence
notices and the regime-conditional buyer-risk warnings). They never
reached the API payload — ``_recommendations_from_decisions`` dropped
them on the floor, so the frontend could not have rendered them even in
principle. These tests pin the wire: warnings ride along when present
and the key stays absent on warning-free decisions (the optional-key
convention used across the report sections).
"""

from __future__ import annotations

from app.services.report_service import ReportService


def _context(decision: dict) -> dict:
    return {"symbols": ["TEST"], "query": "TEST", "decisions": {"TEST": decision}}


def _rec(decision: dict) -> dict:
    sections = ReportService._recommendations_from_decisions(_context(decision))
    return sections["by_symbol"]["TEST"]


class TestRecWarningsPassThrough:
    def test_warnings_reach_the_wire(self) -> None:
        rec = _rec(
            {
                "action": "buy",
                "confidence": 0.6,
                "score": 61.0,
                "warnings": ["Counter-trend entry: benchmark 6.4% below SMA-200"],
            }
        )

        assert rec["warnings"] == ["Counter-trend entry: benchmark 6.4% below SMA-200"]

    def test_warning_free_decision_omits_key(self) -> None:
        rec = _rec({"action": "hold", "confidence": 0.8, "score": 55.0})

        assert "warnings" not in rec

    def test_empty_warning_list_omits_key(self) -> None:
        rec = _rec({"action": "hold", "confidence": 0.8, "score": 55.0, "warnings": []})

        assert "warnings" not in rec
