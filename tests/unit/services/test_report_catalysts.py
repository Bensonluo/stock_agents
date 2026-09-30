"""Catalyst timeline section — buckets, degradation, determinism.

The section surfaces the data layer's ``event_calendar`` (upcoming events)
and ``earnings_surprise`` (last-4 history) per symbol, bucketed 1w/1m/3m
for the frontend timeline card. Pins: relative dates are computed against
``date.today()`` at fixture-build time so the tests never flake on the
calendar; malformed blocks contribute nothing; a symbol with neither
upcoming events nor surprise rows is omitted (optional-key convention).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from app.services.report_service import ReportService


def _day(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def _data(financial: dict[str, Any], symbols: list[str] | None = None) -> dict[str, Any]:
    syms = symbols or ["TEST"]
    return {
        "symbols": syms,
        "query": "catalysts",
        "market_data": {s: {"symbol": s, "current_price": 10.0} for s in syms},
        "financial_data": financial,
    }


def _rich_financial() -> dict[str, Any]:
    return {
        "TEST": {
            "event_calendar": {
                "upcoming": [
                    {"date": _day(40), "type": "dividend", "title": "除息日", "detail": {"amount": 0.25}},
                    {"date": _day(3), "type": "earnings", "title": "财报发布"},
                    {"date": _day(15), "type": "unlock", "title": "限售解禁",
                     "detail": {"shares": 457665903, "pct_of_float": 0.0211}},
                    {"date": _day(-5), "type": "earnings", "title": "过去财报"},  # past → dropped
                    {"date": "not-a-date", "type": "other", "title": "坏行"},  # undated → dropped
                    "garbage-row",  # non-dict → dropped
                ],
                "as_of": _day(0),
            },
            "earnings_surprise": {
                "last_4": [
                    {"date": _day(-90), "estimate": 1.5, "actual": 1.8, "surprise_pct": 0.2},
                    {"date": _day(-180), "estimate": 1.4, "actual": 1.2, "surprise_pct": -0.143},
                ]
            },
        }
    }


class TestCatalystsSection:
    def test_rich_symbol_gets_bucketed_sorted_view(self) -> None:
        sections = ReportService.build_sections(_data(_rich_financial()))
        view = sections["catalysts"]["by_symbol"]["TEST"]

        dates = [event["date"] for event in view["events"]]
        assert dates == sorted(dates)
        assert all(event["days_until"] >= 0 for event in view["events"])
        assert len(view["events"]) == 3  # past + undated + garbage dropped

        first = view["events"][0]
        assert first["type"] == "earnings"
        assert first["bucket"] == "1w"
        assert first["days_until"] == 3
        by_type = {event["type"]: event for event in view["events"]}
        assert by_type["unlock"]["bucket"] == "1m"
        assert by_type["unlock"]["detail"]["pct_of_float"] == 0.0211
        assert by_type["dividend"]["bucket"] == "3m"
        assert "detail" not in first  # detail rides only when present

        assert len(view["earnings_surprise"]) == 2
        assert view["earnings_surprise"][0]["surprise_pct"] == 0.2

    def test_section_absent_when_no_symbols_have_data(self) -> None:
        sections = ReportService.build_sections(_data({}))
        assert "catalysts" not in sections

    def test_symbol_omitted_when_no_upcoming_and_no_surprise(self) -> None:
        financial = {"TEST": {"event_calendar": {"upcoming": [], "as_of": _day(0)}}}
        sections = ReportService.build_sections(_data(financial))
        assert "catalysts" not in sections

    def test_surprise_only_symbol_still_gets_entry(self) -> None:
        financial = {"TEST": {"earnings_surprise": {"last_4": [
            {"date": _day(-30), "estimate": 1.0, "actual": 1.1, "surprise_pct": 0.1}
        ]}}}
        sections = ReportService.build_sections(_data(financial))
        view = sections["catalysts"]["by_symbol"]["TEST"]
        assert view["events"] == []
        assert len(view["earnings_surprise"]) == 1

    def test_malformed_blocks_contribute_nothing(self) -> None:
        financial = {
            "TEST": {
                "event_calendar": "not-a-dict",
                "earnings_surprise": {"last_4": [None, "x", {"no_keys": True}]},
            }
        }
        sections = ReportService.build_sections(_data(financial))
        # last_4 has a dict row → surprise-only entry with empty events
        assert sections["catalysts"]["by_symbol"]["TEST"]["events"] == []

    def test_thin_financial_block_never_raises(self) -> None:
        sections = ReportService.build_sections(_data({"TEST": None}))
        assert "catalysts" not in sections

    def test_later_bucket_and_late_dates(self) -> None:
        financial = {"TEST": {"event_calendar": {"upcoming": [
            {"date": _day(200), "type": "other", "title": "远期事件"},
        ]}}}
        view = ReportService.build_sections(_data(financial))["catalysts"]["by_symbol"]["TEST"]
        assert view["events"][0]["bucket"] == "later"

    def test_multi_symbol_partial_coverage(self) -> None:
        financial = dict(_rich_financial())
        sections = ReportService.build_sections(
            _data(financial, symbols=["TEST", "EMPTY"])
        )
        by_symbol = sections["catalysts"]["by_symbol"]
        assert set(by_symbol) == {"TEST"}  # EMPTY has nothing → omitted

    def test_json_serializable_end_to_end(self) -> None:
        report = ReportService.build_report(_data(_rich_financial()))
        payload = json.dumps(report, ensure_ascii=False)
        assert "catalysts" in report["sections"]
        assert len(payload) > 500
