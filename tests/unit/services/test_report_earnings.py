"""Overview earnings window — the event calendar reaches the report.

Both report paths (pipeline state and ReAct tool payloads) now carry
financial_data; the overview discloses the next scheduled earnings as an
annotation-only block. Degraded conventions: a missing calendar, an empty
one, or a calendar of already-reported quarters omit the key entirely
(same convention as liquidity/sector_relative — absence is absence, not a
default date).
"""

from __future__ import annotations

from datetime import date, timedelta

from app.services.report_service import ReportService

TODAY = date.today()


def _data(financial: dict) -> dict:
    return {
        "symbols": ["TEST"],
        "query": "TEST earnings window",
        "market_data": {"TEST": {"symbol": "TEST", "current_price": 12.34}},
        "financial_data": financial,
    }


class TestOverviewEarningsWindow:
    def test_upcoming_date_disclosed_with_days_until(self) -> None:
        sections = ReportService.build_sections(
            _data(
                {
                    "TEST": {
                        "earnings_dates": [
                            {"date": (TODAY - timedelta(days=40)).isoformat()},
                            {"date": (TODAY + timedelta(days=21)).isoformat()},
                            {"date": (TODAY + timedelta(days=112)).isoformat()},
                        ]
                    }
                }
            )
        )

        earnings = sections["overview"]["market_summary"]["TEST"]["earnings"]
        assert earnings["next_earnings_date"] == (TODAY + timedelta(days=21)).isoformat()
        assert earnings["days_until"] == 21

    def test_no_financial_data_omits_the_key(self) -> None:
        sections = ReportService.build_sections(
            {
                "symbols": ["TEST"],
                "query": "q",
                "market_data": {"TEST": {"symbol": "TEST"}},
            }
        )

        assert "earnings" not in sections["overview"]["market_summary"]["TEST"]

    def test_empty_or_past_calendar_omits_the_key(self) -> None:
        for calendar in ([], [{"date": (TODAY - timedelta(days=5)).isoformat()}]):
            sections = ReportService.build_sections(_data({"TEST": {"earnings_dates": calendar}}))
            assert "earnings" not in sections["overview"]["market_summary"]["TEST"]

    def test_symbol_without_calendar_entry_is_degraded_not_broken(self) -> None:
        sections = ReportService.build_sections(
            _data({"OTHER": {"earnings_dates": [{"date": "2099-01-01"}]}})
        )

        assert "earnings" not in sections["overview"]["market_summary"]["TEST"]
