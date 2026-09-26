"""Risk-committee gate must constrain the published report (存量 P1).

``react_agent`` gates its per-symbol decisions (veto/limit/watch applied)
into ``data["decision"]["decisions"]`` — a flat shape with ``position_size``
as a float percent. ``_normalize`` used to read only the top-level
``decisions`` key, so the ReAct report re-derived recommendations from the
raw analysis scores: a committee-vetoed buy (internally hold, position 0)
shipped as BUY in the published report. These tests pin the corrected read
contract: gated decisions are the single source of truth; top-level
decisions (pipeline shape) remain the fallback.
"""

from __future__ import annotations

from app.services.report_service import ReportService


def _react_data() -> dict:
    """ReAct-shaped report input after a committee veto on stale data.

    The raw analysis scores still support a buy — exactly the inputs the
    old derived path turned into "BUY, confidence 0.72" — but the committee
    verdict downgraded the gated decision to hold with position 0.
    """
    return {
        "query": "Analyze AAPL",
        "symbols": ["AAPL"],
        "market_data": {
            "AAPL": {
                "company_name": "Apple Inc.",
                "current_price": 190.0,
                "currency": "USD",
            },
        },
        "technical_analysis": {
            "AAPL": {
                "signals": {"trend": "bullish", "rsi": "neutral", "macd": "bullish"},
                "sentiment": {"score": 40},
            },
        },
        "fundamental_analysis": {
            "AAPL": {
                "overall_score": {"score": 80, "rating": "good"},
                "recommendation": "buy",
            },
        },
        "sentiment_analysis": {
            "sentiment_by_symbol": {
                "AAPL": {"sentiment": "positive", "score": 30, "article_count": 5},
            },
            "overall_sentiment": {},
        },
        # ReAct risk shape: flat per-symbol, no risk_by_symbol wrapper.
        "risk_assessment": {
            "AAPL": {
                "risk_level": "high",
                "risk_score": 65,
                "metrics": {"volatility_annualized": 0.3, "beta": 1.2},
                "position_recommendation": {"max_position_size": 5.0},
            },
        },
        "decision": {
            "decisions": {
                "AAPL": {
                    "symbol": "AAPL",
                    "action": "hold",
                    "confidence": 0.5,
                    "score": 72.0,
                    "position_size": 0.0,
                    "risk_level": "high",
                    "risk_score": 65,
                    "committee_verdict": "veto",
                    "rationale": "Composite score 72/100; committee=veto",
                },
            }
        },
        "research_synthesis": {},
    }


class TestGatedDecisionsAreThePublishedReport:
    def test_vetoed_decision_overrides_derived_buy(self) -> None:
        sections = ReportService.build_sections(_react_data())

        rec = sections["recommendations"]["by_symbol"]["AAPL"]
        assert rec["action"] == "hold"
        assert rec["confidence"] == 0.5
        # Flat float position_size normalized through, not crashed on.
        assert rec["position_size"] == 0.0

    def test_vetoed_symbol_gets_no_portfolio_allocation(self) -> None:
        sections = ReportService.build_sections(_react_data())

        # Hold is not a buy candidate — fewer than two eligible, no block.
        assert sections["recommendations"]["suggested_weights"] is None

    def test_executive_summary_states_the_gated_action(self) -> None:
        report = ReportService.build_report(_react_data())

        assert "HOLD" in report["executive_summary"]
        assert "BUY" not in report["executive_summary"]

    def test_pipeline_top_level_decisions_still_used(self) -> None:
        # report_agent unwraps state["decision"]["decisions"] into the
        # top-level key before calling the service; that legacy shape keeps
        # working when no nested "decision" wrapper is present.
        data = _react_data()
        data["decisions"] = data.pop("decision")["decisions"]

        rec = ReportService.build_sections(data)["recommendations"]["by_symbol"]["AAPL"]

        assert rec["action"] == "hold"
        assert rec["position_size"] == 0.0

    def test_nested_gate_wins_over_stale_top_level_decisions(self) -> None:
        # Both keys present (e.g. a stale pre-gate snapshot riding along):
        # the nested gated map is the fresher, authoritative one.
        data = _react_data()
        data["decisions"] = {
            "AAPL": {
                "action": "strong_buy",
                "confidence": 0.88,
                "score": 90,
                "position_size": {"percentage_of_portfolio": 20},
            }
        }

        rec = ReportService.build_sections(data)["recommendations"]["by_symbol"]["AAPL"]

        assert rec["action"] == "hold"
        assert rec["position_size"] == 0.0
