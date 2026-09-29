"""End-to-end transmission of assess_risk's run-level annotation blocks.

The production ReAct tool returns the flat multi-symbol shape
``{symbol: entry, market_regime: {...}, option_implied: {...}}``; the
executor's dict-merge branch parks all three in the ``assess_risk``
bucket, ``_build_report_data`` copies the bucket into
``data["risk_assessment"]``, and the report layer lifts BOTH namespace
keys into the risk section while keeping ``by_symbol`` purely
per-symbol. This pins the full production transport that was broken
before iteration 156: the legacy multi-symbol tool that attached the
regime had zero production callers, so ReAct reports never saw either
annotation block.
"""

from __future__ import annotations

from app.react_agent import react_agent
from app.services.report_service import ReportService

BEAR_REGIME = {
    "status": "ok",
    "bars": 210,
    "trend": "bear",
    "price_vs_sma200": -0.417,
    "volatility_regime": "normal",
    "drawdown_from_52w_high": -0.05,
}

OPTION_IMPLIED = {
    "status": "ok",
    "regime": "恐慌",
    "qvix": {"current": 25.0, "as_of": "2026-09-29", "percentile_1y": 0.9, "history_days": 500},
    "iv": None,
    "pcr": None,
    "generated_at": "2026-09-29T12:00:00",
}

RISK_ENTRY = {"symbol": "600000", "risk_score": 45, "risk_level": "medium", "metrics": {}}


def _state() -> dict:
    return {
        "symbols": ["600000"],
        "query": "600000",
        "tool_results": {
            "assess_risk": {
                "600000": RISK_ENTRY,
                "market_regime": BEAR_REGIME,
                "option_implied": OPTION_IMPLIED,
            },
        },
    }


def test_react_transmission_delivers_both_annotations_to_risk_section() -> None:
    data = react_agent._build_report_data(_state())

    sections = ReportService.build_sections(data)
    risk = sections["risk_analysis"]

    assert risk["market_regime"]["status"] == "ok"
    assert risk["option_implied"]["regime"] == "恐慌"
    # Namespace keys lifted out — by_symbol stays exactly per-symbol, so
    # downstream per-symbol consumers (position sizing) never trip on them.
    assert list(risk["by_symbol"].keys()) == ["600000"]
