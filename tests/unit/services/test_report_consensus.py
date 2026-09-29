"""CN analyst-consensus block transmission through the report fundamental section.

The report is the frontend's only wire: a consensus block that dies in
``_fundamental`` can never render. Mirrors the option_implied/liquidity
pass-through contract — a present block rides the per-symbol fundamental
card, an absent block adds no key, and the composite fundamental rating
never reads it.
"""

from __future__ import annotations

from app.services.report_service import ReportService

_CONSENSUS = {
    "status": "ok",
    "eps_forecast": {
        "year1": 2026,
        "eps_mean": 2.15,
        "org_count": 12,
        "industry_avg": 1.87,
        "year2": 2027,
        "eps_mean_year2": 2.40,
        "implied_growth": 0.1163,
    },
    "target_price": {
        "count": 5,
        "mean": 12.5,
        "median": 12.0,
        "implied_upside": 0.3647,
        "window_days": 180,
    },
    "ratings": {
        "counts": {"买入": 4, "增持": 1, "中性": 0, "减持": 0, "卖出": 0},
        "dominant": "买入",
        "total": 5,
    },
}


def _data(consensus: dict | None) -> dict:
    financial: dict = {"600000": {"metrics": {"pe_ratio": 5.2}}}
    if consensus is not None:
        financial["600000"]["consensus"] = consensus
    return {
        "symbols": ["600000"],
        "query": "A股分析",
        "financial_data": financial,
        "fundamental_analysis": {
            "600000": {
                "overall_score": {"score": 72, "rating": "buy"},
                "recommendation": "buy",
                "profitability": {"rating": "strong"},
                "valuation": {"rating": "cheap"},
                "financial_health": {"rating": "healthy"},
            }
        },
    }


class TestConsensusPassthrough:
    def test_consensus_block_reaches_the_report(self) -> None:
        sections = ReportService.build_sections(_data(_CONSENSUS))

        card = sections["fundamental_analysis"]["by_symbol"]["600000"]
        assert card["overall_score"] == 72
        assert card["consensus"]["eps_forecast"]["eps_mean"] == 2.15
        assert card["consensus"]["target_price"]["implied_upside"] == 0.3647
        assert card["consensus"]["ratings"]["dominant"] == "买入"

    def test_absent_block_adds_no_key_and_leaves_rating_alone(self) -> None:
        sections = ReportService.build_sections(_data(None))

        section = sections["fundamental_analysis"]
        assert "consensus" not in section["by_symbol"]["600000"]
        # The composite rating is score-derived — consensus absence must not
        # touch it (pure-annotation contract).
        assert section["overall_rating"] == "buy"

    def test_block_does_not_shift_the_composite_rating(self) -> None:
        """Same scores, consensus present vs absent → identical rating path."""
        with_block = ReportService.build_sections(_data(_CONSENSUS))["fundamental_analysis"]
        without_block = ReportService.build_sections(_data(None))["fundamental_analysis"]

        assert with_block["overall_rating"] == without_block["overall_rating"]
        scored_with = with_block["by_symbol"]["600000"]["overall_score"]
        scored_without = without_block["by_symbol"]["600000"]["overall_score"]
        assert scored_with == scored_without == 72
