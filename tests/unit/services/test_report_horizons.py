"""Per-horizon decision term structure — drivers, window catalysts, watch.

The single decision must not fork into conflicting per-horizon actions; the
horizons block explains its term structure instead: which analysis layers
dominate each window (fixed, stated mapping), the nearest catalyst landing
inside it, and deterministic watch lines from measured data. A symbol whose
windows carry no catalyst and no watch line is omitted entirely.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from app.services.report_service import ReportService


def _day(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def _data(extra: dict[str, Any]) -> dict[str, Any]:
    base: dict[str, Any] = {
        "symbols": ["TEST"],
        "query": "horizons",
        "market_data": {"TEST": {"symbol": "TEST", "current_price": 10.0}},
    }
    base.update(extra)
    return base


def _rich_extra() -> dict[str, Any]:
    return {
        "financial_data": {
            "TEST": {
                "event_calendar": {
                    "upcoming": [
                        {"date": _day(3), "type": "earnings", "title": "财报发布"},
                        {"date": _day(15), "type": "unlock", "title": "限售解禁"},
                        {"date": _day(40), "type": "dividend", "title": "除息日"},
                        {"date": _day(200), "type": "other", "title": "远期事项"},
                    ],
                    "as_of": _day(0),
                }
            }
        },
        "technical_analysis": {
            "TEST": {
                "signals": {"trend": "bullish"},
                "sentiment": {"score": 30},
                "weekly_sma": {
                    "status": "available",
                    "as_of": _day(0),
                    "alignment": {"state": "bullish", "weeks_in_state": 6},
                    "sma": {"20": {"warm_up_met": True, "distance_pct": 3.2}},
                    "crosses": {
                        "sma_20_40": {"status": "observed", "direction": "golden", "weeks_since": 3}
                    },
                },
            }
        },
        "fundamental_analysis": {
            "TEST": {
                "overall_score": {"score": 72.0, "rating": "good"},
                "recommendation": "buy",
                "valuation_scenarios": {
                    "status": "available",
                    "as_of": _day(0),
                    "methods": {
                        "earnings_multiple": {
                            "scenarios": {
                                "bear": {"value": 210.0, "upside_pct": -29.0},
                                "base": {"value": 305.0, "upside_pct": 3.2},
                                "bull": {"value": 365.0, "upside_pct": 23.5},
                            }
                        }
                    },
                },
                "quality": {
                    "status": "available",
                    "revenue_trend": {"cagr": 0.08},
                    "cash_quality": {"cfo_to_net_income": 1.1},
                    "red_flags": [{"severity": "warning", "name": "revenue_decline"}],
                },
            }
        },
        "sentiment_analysis": {
            "TEST": {"sentiment": "positive", "score": 40, "trend": "stable", "article_count": 12}
        },
        "risk_analysis": {"TEST": {"risk_level": "medium", "risk_score": 40}},
        "research_synthesis": {
            "per_symbol": {"TEST": {"debate": {"invalidation": "连续两季营收同比转负"}}}
        },
    }


class TestHorizonViews:
    def test_windows_carry_nearest_catalyst_and_watch(self) -> None:
        summary = ReportService.build_sections(_data(_rich_extra()))["recommendations"]
        horizons = summary["horizons"]["TEST"]

        assert horizons["1w"]["drivers"] == ["technical", "sentiment"]
        assert horizons["1m"]["drivers"] == ["technical", "fundamental", "sentiment"]
        assert horizons["3m"]["drivers"] == ["fundamental", "risk"]

        assert horizons["1w"]["catalyst"]["days_until"] == 3
        assert horizons["1w"]["catalyst"]["type"] == "earnings"
        assert horizons["1m"]["catalyst"]["days_until"] == 15
        assert horizons["3m"]["catalyst"]["days_until"] == 40

        watch_1w = " ".join(horizons["1w"]["watch"])
        assert "周线排列bullish" in watch_1w and "持续6周" in watch_1w
        assert "金叉" in watch_1w

        assert any(
            "情景区间" in line and "-29%" in line and "+24%" in line
            for line in horizons["1m"]["watch"]
        )

        watch_3m = " ".join(horizons["3m"]["watch"])
        assert "红旗1项" in watch_3m
        assert "失效条件: 连续两季营收同比转负" in watch_3m

    def test_events_beyond_all_windows_produce_later_only(self) -> None:
        extra = _rich_extra()
        extra["financial_data"]["TEST"]["event_calendar"]["upcoming"] = [
            {"date": _day(200), "type": "other", "title": "远期事项"}
        ]
        horizons = ReportService.build_sections(_data(extra))["recommendations"]["horizons"]["TEST"]
        for horizon in ("1w", "1m", "3m"):
            assert "catalyst" not in horizons[horizon]
        # 200d out is beyond 3m — no window claims it.
        assert all("catalyst" not in h for h in horizons.values())

    def test_symbol_omitted_when_windows_are_empty(self) -> None:
        summary = ReportService.build_sections(_data({}))["recommendations"]
        assert "horizons" not in summary

    def test_catalyst_only_symbol_still_gets_horizons(self) -> None:
        extra = {
            "financial_data": {
                "TEST": {
                    "event_calendar": {
                        "upcoming": [{"date": _day(5), "type": "earnings", "title": "财报发布"}]
                    }
                }
            }
        }
        horizons = ReportService.build_sections(_data(extra))["recommendations"]["horizons"]["TEST"]
        assert horizons["1w"]["catalyst"]["type"] == "earnings"
        assert "catalyst" not in horizons["3m"]

    def test_insufficient_weekly_pack_never_fakes_watch(self) -> None:
        extra = _rich_extra()
        extra["technical_analysis"]["TEST"]["weekly_sma"] = {
            "status": "insufficient_data",
            "reason": "thin history",
        }
        extra["financial_data"] = {}
        extra["fundamental_analysis"]["TEST"].pop("valuation_scenarios")
        extra["fundamental_analysis"]["TEST"]["quality"] = {
            "status": "available",
            "revenue_trend": {},
            "cash_quality": {},
            "red_flags": [],
        }
        extra["research_synthesis"] = {}
        summary = ReportService.build_sections(_data(extra))["recommendations"]
        assert "horizons" not in summary  # nothing measured anywhere → omitted

    def test_deterministic_and_json_safe(self) -> None:
        first = ReportService.build_report(_data(_rich_extra()))
        second = ReportService.build_report(_data(_rich_extra()))
        h1 = first["sections"]["recommendations"]["horizons"]
        h2 = second["sections"]["recommendations"]["horizons"]
        assert h1 == h2
        json.dumps(h1, ensure_ascii=False)
