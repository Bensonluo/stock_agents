"""Fundamental trend annotations — iteration 190's multi-period history
(indicators_history / statements_quarterly) consumed at the analysis seam.

Contract pins:
    CN indicators_history rows are YTD-cumulative → the ONLY honest
    comparison is same-period-prior-year; no anchor = no block, never a
    quarter-over-quarter fake.
    US/HK quarterly statements are discrete quarters → QoQ is valid.
    Pure annotation: a trend block changes no score, and scoring output
    with history stripped drops the key and nothing else.
"""

from __future__ import annotations

import math
from typing import Any

from app.analysis.fundamental.scoring import analyze_fundamental_scoring
from app.analysis.fundamental.trends import (
    quarterly_statement_trends,
    trend_annotation,
    yoy_metric_trends,
)
from app.services.report_service import ReportService


def _cn_history() -> list[dict[str, Any]]:
    """Ascending dated rows — the shape _sync_fetch_akshare_financials emits."""
    return [
        {"date": "2025-09-30", "metrics": {"roe": 0.28, "profit_margin": 0.49}},
        {"date": "2026-06-30", "metrics": {"roe": 0.30, "profit_margin": 0.50}},
        {
            "date": "2026-09-30",
            "metrics": {"roe": 0.31, "profit_margin": 0.49, "revenue_growth": 0.09},
        },
    ]


# --------------------------------------------------------------------------
# CN: same-period-prior-year
# --------------------------------------------------------------------------


def test_cn_yoy_anchors_latest_against_same_period_prior_year() -> None:
    trend = yoy_metric_trends(_cn_history())

    assert trend is not None
    assert trend["basis"] == "same_period_prior_year"
    assert trend["as_of"] == "2026-09-30"
    # 2026-09-30 vs 2025-09-30 — the 2026-06-30 row must not be the anchor.
    assert trend["metrics"]["roe"] == {
        "value": 0.31,
        "year_ago": 0.28,
        "delta": 0.31 - 0.28,
        "direction": "improving",
    }
    assert trend["metrics"]["profit_margin"]["direction"] == "flat"
    # revenue_growth has no 2025 counterpart → omitted, not fabricated.
    assert "revenue_growth" not in trend["metrics"]


def test_cn_yoy_without_prior_anchor_returns_none() -> None:
    """A single year of rows (or a leap-day latest with no 02-29 prior) has
    no honest YoY anchor — None, never a nearest-row stand-in."""
    single_year = [
        {"date": "2026-03-31", "metrics": {"roe": 0.30}},
        {"date": "2026-09-30", "metrics": {"roe": 0.31}},
    ]
    leap_latest = [
        {"date": "2024-02-28", "metrics": {"roe": 0.30}},
        {"date": "2024-02-29", "metrics": {"roe": 0.31}},
    ]

    assert yoy_metric_trends(single_year) is None
    assert yoy_metric_trends(leap_latest) is None
    assert yoy_metric_trends([]) is None
    assert yoy_metric_trends(None) is None


def test_cn_yoy_deteriorating_direction() -> None:
    trend = yoy_metric_trends(
        [
            {"date": "2025-09-30", "metrics": {"roe": 0.31}},
            {"date": "2026-09-30", "metrics": {"roe": 0.28}},
        ]
    )

    assert trend["metrics"]["roe"]["direction"] == "deteriorating"
    assert math.isclose(trend["metrics"]["roe"]["delta"], -0.03)


# --------------------------------------------------------------------------
# US/HK: quarter-over-quarter off the converted statement block
# --------------------------------------------------------------------------


def _income_block() -> dict[str, Any]:
    """Converter shape {dates, data} — deliberately unsorted newest-first
    (yfinance order) with a NaN hole and a stale 5th quarter that the
    4-quarter window must drop."""
    return {
        "dates": ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"],
        "data": {
            "Total Revenue": [123.0, 100.0, 98.0, float("nan"), 90.0],
            "Net Income": [45.0, float("nan"), 40.0, 38.0, 35.0],
            "Ignored Row": [1.0, 2.0, 3.0, 4.0, 5.0],
        },
    }


def test_quarterly_trend_reads_qoq_off_the_income_block() -> None:
    trend = quarterly_statement_trends({"income_statement": _income_block()})

    assert trend is not None
    assert trend["basis"] == "quarter_over_quarter"
    revenue = trend["metrics"]["revenue"]
    # Window = last 4 quarters, presented oldest→newest, NaN quarter skipped
    # per-metric; latest QoQ is 123 − 100 despite the 98 sitting between them
    # in calendar order only because 2026-03-31 is the prior quarter.
    assert [(q["quarter"], q["value"]) for q in revenue["quarters"]] == [
        ("2025-12-31", 98.0),
        ("2026-03-31", 100.0),
        ("2026-06-30", 123.0),
    ]
    assert math.isclose(revenue["latest_qoq_delta"], 23.0)
    assert revenue["direction"] == "improving"
    # Net Income keeps its own series inside the SAME 4-quarter window:
    # 2026-03-31's NaN drops out of its pairs only.
    assert [(q["quarter"], q["value"]) for q in trend["metrics"]["net_income"]["quarters"]] == [
        ("2025-09-30", 38.0),
        ("2025-12-31", 40.0),
        ("2026-06-30", 45.0),
    ]
    assert "Ignored Row" not in trend["metrics"]


def test_quarterly_trend_degraded_inputs_return_none() -> None:
    """Missing block, empty dates, or no row with two valid points → None."""
    assert quarterly_statement_trends(None) is None
    assert quarterly_statement_trends({}) is None
    assert quarterly_statement_trends({"income_statement": {"dates": [], "data": {}}}) is None
    sparse = {"dates": ["2026-06-30"], "data": {"Total Revenue": [1.0]}}
    assert quarterly_statement_trends({"income_statement": sparse}) is None


# --------------------------------------------------------------------------
# Scoring seam wiring (pipeline + ReAct share it) + purity pin
# --------------------------------------------------------------------------


_METRICS = {
    "roe": 0.31,
    "profit_margin": 0.49,
    "pe_ratio": 20.0,
    "debt_to_equity": 0.5,
    "current_ratio": 2.0,
    "revenue_growth": 0.09,
}


def test_scoring_attaches_trend_as_a_pure_annotation() -> None:
    """The same metrics with and without history: every score bit-for-bit
    identical, the trend block the ONLY difference."""
    with_history = analyze_fundamental_scoring(
        {"600519": {"metrics": dict(_METRICS), "indicators_history": _cn_history()}}
    )
    without = analyze_fundamental_scoring({"600519": {"metrics": dict(_METRICS)}})

    a, b = with_history["600519"], without["600519"]
    for key in ("profitability", "valuation", "financial_health", "growth", "overall_score"):
        assert a[key] == b[key], f"{key} moved — trend annotation is not pure"
    assert a["trend"]["basis"] == "same_period_prior_year"
    assert "trend" not in b


def test_scoring_prefers_cn_history_and_falls_back_to_quarterly() -> None:
    cn = trend_annotation({"indicators_history": _cn_history()})
    assert cn is not None and cn["basis"] == "same_period_prior_year"

    us = trend_annotation({"statements_quarterly": {"income_statement": _income_block()}})
    assert us is not None and us["basis"] == "quarter_over_quarter"

    assert trend_annotation({"metrics": {}}) is None


# --------------------------------------------------------------------------
# Report-layer passthrough
# --------------------------------------------------------------------------


def test_report_fundamental_passes_the_trend_block_through() -> None:
    trend = trend_annotation({"indicators_history": _cn_history()})
    section = ReportService._fundamental(
        {
            "fundamental_analysis": {
                "600519": {
                    "overall_score": {"score": 75, "rating": "good"},
                    "recommendation": "buy",
                    "trend": trend,
                }
            },
            "financial_data": {},
        }
    )

    assert section["by_symbol"]["600519"]["trend"] is trend


def test_report_fundamental_without_trend_adds_no_key() -> None:
    section = ReportService._fundamental(
        {
            "fundamental_analysis": {
                "600519": {
                    "overall_score": {"score": 75, "rating": "good"},
                    "recommendation": "buy",
                }
            },
            "financial_data": {},
        }
    )

    assert "trend" not in section["by_symbol"]["600519"]
