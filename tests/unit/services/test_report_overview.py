"""Overview currency/market-cap pass-through.

The frontend priced every market overview and trade plan in dollars —
A-share prices rendered as "$12.34". The currency key existed in provider
snapshots (Finnhub) or was one line away (yfinance info), but ``_overview``
never carried it. These tests pin the wire: currency and market_cap reach
the report when the market block has them; degraded blocks report None.
"""

from __future__ import annotations

from app.services.report_service import ReportService


def _data(mkt: dict) -> dict:
    return {
        "symbols": ["TEST"],
        "query": "TEST overview",
        "market_data": {"TEST": mkt},
    }


class TestOverviewCurrencyPassThrough:
    def test_currency_and_market_cap_reach_the_report(self) -> None:
        sections = ReportService.build_sections(
            _data(
                {
                    "symbol": "TEST",
                    "current_price": 12.34,
                    "currency": "CNY",
                    "market_cap": 2.5e11,
                }
            )
        )

        info = sections["overview"]["market_summary"]["TEST"]
        assert info["currency"] == "CNY"
        assert info["market_cap"] == 2.5e11
        assert info["current_price"] == 12.34

    def test_degraded_block_reports_none_not_garbage(self) -> None:
        sections = ReportService.build_sections(_data({"symbol": "TEST"}))

        info = sections["overview"]["market_summary"]["TEST"]
        assert info["currency"] is None
        assert info["market_cap"] is None
