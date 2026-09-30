"""Eval harness: analyst-consensus annotation regression gates (iteration 168).

The consensus arc — CN attach + report passthrough (163), browser render
(166), US ratings-only twin with market dispatch (167) — locked here
end-to-end at the product level, in the option-annotation gates' tradition
(iteration 161): the REAL analysis -> risk -> decision -> report chain runs
on a synthetic CN state with a wire-ready ``consensus`` dict injected into
``financial_data`` at state top level (the data agent attaches it there per
symbol in production; no network anywhere in this harness, no LLM).

Three contracts under gate:
    1. Transmission — the consensus block rides the report's fundamental
       section per symbol with its full nested shape (eps_forecast /
       target_price / ratings), and the graded report still passes.
    2. Honest degradation — the US twin's production shape (ratings-only,
       status insufficient_data, no EPS/target rows) survives the same
       wire; the report never upgrades or drops it.
    3. Pure annotation — the identical state WITHOUT the block yields
       bit-identical decisions and fundamental scores; the block may only
       add a ``consensus`` key, never touch a number.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.eval.rubric import grade_report
from tests.integration.test_pipeline_flow import _load, _synthetic_state

pytestmark = pytest.mark.asyncio

CN = "600519"


# ---------------------------------------------------------------------------
# Fixtures (hermetic: wire-ready dicts mirroring app/tools/data/consensus.py)
# ---------------------------------------------------------------------------


def _full_consensus() -> dict[str, Any]:
    """One synthetic CN ok block — every sub-block present. Values mirror the
    frontend component pins (report-shared.test.tsx) so both ends of the wire
    assert the same fixture."""
    return {
        "status": "ok",
        "eps_forecast": {
            "year1": 2026,
            "eps_mean": 2.15,
            "org_count": 5,
            "industry_avg": 2.31,
            "year2": 2027,
            "eps_mean_year2": 2.28,
            "implied_growth": round(2.28 / 2.15 - 1, 4),
        },
        "target_price": {
            "count": 12,
            "mean": 12.5,
            "median": 12.0,
            "window_days": 180,
            "implied_upside": 0.032,
        },
        "ratings": {
            "counts": {"买入": 12, "增持": 8, "中性": 0, "减持": 0, "卖出": 0},
            "dominant": "买入",
            "total": 20,
        },
    }


def _ratings_only_consensus() -> dict[str, Any]:
    """The US twin's production shape (iteration 167): Finnhub monthly band
    snapshots carry no hard EPS/target evidence, so the block is ratings-only
    and honestly labeled insufficient_data."""
    return {
        "status": "insufficient_data",
        "ratings": {
            "counts": {"买入": 7, "增持": 13, "中性": 2, "减持": 0, "卖出": 0},
            "dominant": "增持",
            "total": 22,
        },
    }


def _cn_state() -> dict[str, Any]:
    """Fresh single-CN-symbol state (seeded: deterministic decision band)."""
    return _synthetic_state(CN)


def _with_consensus(block: dict[str, Any]) -> dict[str, Any]:
    state = _cn_state()
    state["financial_data"][CN]["consensus"] = block
    return state


async def _run_pipeline(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The real agent chain in orchestrator order, llm=None — the eval
    harness wiring (test_report_eval's runner, no asyncio.run nesting)."""

    def make(module, cls_name):
        agent = getattr(module, cls_name)()
        agent.llm = None  # deterministic: no LLM in the eval gate
        return agent

    analysis_mod = _load("analysis_agent.py", "csgate_analysis_agent")
    sentiment_mod = _load("sentiment_agent.py", "csgate_sentiment_agent")
    risk_mod = _load("risk_agent.py", "csgate_risk_agent")
    synthesis_mod = _load("synthesis_agent.py", "csgate_synthesis_agent")
    decision_mod = _load("decision_agent.py", "csgate_decision_agent")
    report_mod = _load("report_agent.py", "csgate_report_agent")

    state.update(await make(analysis_mod, "TechnicalAnalysisAgent").execute(state))
    state.update(await make(analysis_mod, "FundamentalAnalysisAgent").execute(state))
    state["sentiment_analysis"] = await make(sentiment_mod, "SentimentAnalysisAgent").process(state)
    state["risk_assessment"] = await make(risk_mod, "RiskAssessmentAgent").process(state)
    state.update(await make(synthesis_mod, "ResearchSynthesisAgent").process(state))
    state["decision"] = await make(decision_mod, "DecisionMakingAgent").process(state)
    report = await make(report_mod, "ReportGenerationAgent").process(state)
    return state, report


def _grade(state: dict[str, Any], report: dict[str, Any]):
    return grade_report(
        report,
        decisions=(state.get("decision") or {}).get("decisions", {}),
        symbols=state.get("symbols", []),
    )


# ---------------------------------------------------------------------------
# Contract 1 — transmission (full CN block)
# ---------------------------------------------------------------------------


class TestTransmission:
    async def test_full_block_reaches_report_fundamental_section(self):
        state, report = await _run_pipeline(_with_consensus(_full_consensus()))
        result = _grade(state, report)
        assert result.passed, result.summary()

        entry = report["sections"]["fundamental_analysis"]["by_symbol"][CN]
        block = entry["consensus"]
        assert block["status"] == "ok"

        # The full pipeline-nested shape survives the wire, not just a label.
        eps = block["eps_forecast"]
        assert eps["year1"] == 2026
        assert eps["eps_mean"] == pytest.approx(2.15)
        assert eps["org_count"] == 5
        assert eps["industry_avg"] == pytest.approx(2.31)
        assert eps["implied_growth"] == pytest.approx(round(2.28 / 2.15 - 1, 4))

        tp = block["target_price"]
        assert tp["count"] == 12
        assert tp["mean"] == pytest.approx(12.5)
        assert tp["implied_upside"] == pytest.approx(0.032)

        ratings = block["ratings"]
        assert ratings["counts"]["买入"] == 12
        assert ratings["dominant"] == "买入"
        assert ratings["total"] == 20


# ---------------------------------------------------------------------------
# Contract 2 — honest degradation (US ratings-only twin shape)
# ---------------------------------------------------------------------------


class TestRatingsOnlyDegradation:
    async def test_ratings_only_block_survives_the_wire_unmodified(self):
        """The US twin's production form: ratings-only, insufficient_data.
        The report must carry it exactly — never upgrade the status, never
        fabricate EPS/target rows the block does not have."""
        state, report = await _run_pipeline(_with_consensus(_ratings_only_consensus()))
        result = _grade(state, report)
        assert result.passed, result.summary()

        block = report["sections"]["fundamental_analysis"]["by_symbol"][CN]["consensus"]
        assert block["status"] == "insufficient_data"
        assert "eps_forecast" not in block
        assert "target_price" not in block
        assert block["ratings"]["dominant"] == "增持"
        assert block["ratings"]["total"] == 22


# ---------------------------------------------------------------------------
# Pure-annotation pin — the arc's design red line
# ---------------------------------------------------------------------------


class TestPureAnnotationPin:
    async def test_without_block_numbers_are_bit_identical(self):
        """The consensus block may only ADD a report key. The identical
        state minus the block must produce decisions with bit-identical
        action/score/confidence and the same fundamental section score —
        annotation never touches numbers."""
        s_with, r_with = await _run_pipeline(_with_consensus(_full_consensus()))
        s_without, r_without = await _run_pipeline(_cn_state())

        d_with = s_with["decision"]["decisions"][CN]
        d_without = s_without["decision"]["decisions"][CN]
        assert d_with["action"] == d_without["action"]
        assert d_with["score"] == d_without["score"]  # ==, not approx: bit-identical
        assert d_with["confidence"] == d_without["confidence"]

        # Fundamental section: same score, same aggregate rating — the block
        # only adds its own key to the per-symbol entry.
        entry_with = r_with["sections"]["fundamental_analysis"]["by_symbol"][CN]
        entry_without = r_without["sections"]["fundamental_analysis"]["by_symbol"][CN]
        assert entry_with["overall_score"] == entry_without["overall_score"]
        assert (
            r_with["sections"]["fundamental_analysis"]["overall_rating"]
            == r_without["sections"]["fundamental_analysis"]["overall_rating"]
        )

        # The annotation's whole effect is the key's presence.
        assert "consensus" in entry_with
        assert "consensus" not in entry_without
