"""Option-implied block transmission through the report risk section.

The report is the frontend's only wire: an annotation block that dies in
``_risk`` can never render. Mirrors the liquidity/sector_relative
pass-through contract — present blocks ride the run-level risk section,
absent blocks add no keys.
"""

from __future__ import annotations

from app.services.report_service import ReportService

_OPTION_IMPLIED = {
    "status": "ok",
    "regime": "中性",
    "qvix": {"current": 21.0, "as_of": "2026-09-29", "percentile_1y": 0.45},
    "iv": {"atm_iv_near": 0.185, "term_structure": -0.025, "skew_25d": 0.0375},
    "pcr": {"market_pcr": 0.9},
    "generated_at": "2026-09-30T10:00:00",
}


def _risk_entry() -> dict:
    return {
        "symbol": "600000",
        "risk_score": 42.0,
        "risk_level": "medium",
        "risk_score_status": "complete",
        "metrics": {"beta": 1.1, "volatility_annualized": 0.28},
        "position_recommendation": {"max_position_size": 10.0, "status": "available"},
        "warnings": [],
    }


def _data(option_implied: dict | None) -> dict:
    risk: dict = {
        "risk_by_symbol": {"600000": _risk_entry()},
        "portfolio_risk": {},
        "overall_risk_level": "medium",
        "market_regime": {"status": "ok", "trend": "sideways"},
    }
    if option_implied is not None:
        risk["option_implied"] = option_implied
    return {
        "symbols": ["600000"],
        "query": "A股分析",
        "risk_assessment": risk,
    }


class TestOptionImpliedPassthrough:
    def test_option_implied_block_reaches_the_report(self) -> None:
        sections = ReportService.build_sections(_data(_OPTION_IMPLIED))

        risk_section = sections["risk_analysis"]
        assert risk_section["option_implied"]["regime"] == "中性"
        assert risk_section["option_implied"]["qvix"]["percentile_1y"] == 0.45
        # The per-symbol card is untouched by the market-level block.
        assert risk_section["by_symbol"]["600000"]["risk_score"] == 42.0

    def test_absent_block_adds_no_key(self) -> None:
        sections = ReportService.build_sections(_data(None))

        assert "option_implied" not in sections["risk_analysis"]
        assert sections["risk_analysis"]["market_regime"]["status"] == "ok"
