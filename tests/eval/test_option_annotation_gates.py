"""Eval harness: option-annotation arc regression gates (iteration 161).

The CN option-implied arc — data attach + risk label (155), ReAct parity +
frontend render (156), decision warnings + synthesis context (158), frontend
component pins (159) — locked here end-to-end at the product level, in the
market_regime gates' tradition: the REAL risk -> decision -> report chain
runs on a synthetic CN state with a synthetic ``option_snapshot`` injected
at state top level (the risk node is pure compute over it by design — no
network anywhere in this harness, no LLM).

Three contracts under gate:
    1. Transmission — the option_implied block rides the report's risk
       section with the right regime label (恐慌/自满) and its full nested
       shape (qvix / iv / pcr).
    2. Buy warnings — a buy-band decision under a non-neutral option regime
       must carry the option-market warning, in the pipeline decisions AND
       the report's recommendation cards.
    3. Pure annotation — the identical state WITHOUT the snapshot yields
       bit-identical action/score/confidence; the annotation may only
       append warning strings, never touch numbers.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.eval.rubric import grade_report
from tests.integration.test_pipeline_flow import _load, _synthetic_state

pytestmark = pytest.mark.asyncio

CN = "600519"


# ---------------------------------------------------------------------------
# Fixtures (hermetic: synthetic dicts only, deterministic by construction)
# ---------------------------------------------------------------------------


def _contracts() -> list[dict[str, Any]]:
    """16-row SSE-shaped surface across two expiries.

    Enough usable rows (>= 10) for compute_iv_metrics to build ATM IV, term
    structure and 25-delta skew; deltas stay inside the |0.98| filter and
    the put/call wings straddle the 0.15-0.35 skew band on the near expiry.
    """

    def row(expiry: str, cp: str, strike: float, delta: float, iv: float) -> dict[str, Any]:
        return {
            "contract_id": f"{expiry.replace('-', '')}{cp}{int(strike * 1000):06d}",
            "symbol": "510050",
            "cp": cp,
            "strike": strike,
            "expire_date": expiry,
            "delta": delta,
            "iv": iv,
        }

    near, nxt = "2026-10-28", "2026-11-25"
    near_rows = [
        ("C", 2.90, 0.60),
        ("C", 2.95, 0.50),
        ("C", 3.00, 0.35),
        ("C", 3.05, 0.25),
        ("P", 2.90, -0.20),
        ("P", 2.85, -0.30),
        ("P", 2.80, -0.40),
        ("P", 2.75, -0.65),
    ]
    next_rows = [
        ("C", 2.90, 0.58),
        ("C", 2.95, 0.48),
        ("C", 3.00, 0.33),
        ("C", 3.05, 0.23),
        ("P", 2.90, -0.22),
        ("P", 2.85, -0.32),
        ("P", 2.80, -0.42),
        ("P", 2.75, -0.66),
    ]
    return [
        row(near, cp, strike, delta, 0.18 + 0.002 * i)
        for i, (cp, strike, delta) in enumerate(near_rows)
    ] + [
        row(nxt, cp, strike, delta, 0.20 + 0.002 * i)
        for i, (cp, strike, delta) in enumerate(next_rows)
    ]


def _option_snapshot(percentile: float, current: float) -> dict[str, Any]:
    """One synthetic CN run-level snapshot; the percentile picks the regime
    (>= 0.80 恐慌, <= 0.20 自满 — build_option_implied's only regime input)."""
    return {
        "status": "ok",
        "as_of": "2026-09-29",
        "contracts": _contracts(),
        "pcr_by_underlying": {
            "510050": {
                "name": "上证50ETF",
                "pcr_volume": 0.9,
                "call_volume": 1_000_000.0,
                "put_volume": 900_000.0,
                "trade_date": "2026-09-29",
            },
            "510300": {
                "name": "沪深300ETF",
                "pcr_volume": 1.1,
                "call_volume": 2_000_000.0,
                "put_volume": 2_200_000.0,
                "trade_date": "2026-09-29",
            },
        },
        "n_unmatched": 0,
        "qvix_context": {
            "current": current,
            "as_of": "2026-09-29",
            "percentile_1y": percentile,
            "history_days": 252,
        },
    }


def _cn_state() -> dict[str, Any]:
    """Fresh single-CN-symbol state (seeded: deterministic buy band)."""
    return _synthetic_state(CN)


async def _run_pipeline(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The real agent chain in orchestrator order, llm=None — the eval
    harness wiring (test_report_eval's runner, no asyncio.run nesting)."""

    def make(module, cls_name):
        agent = getattr(module, cls_name)()
        agent.llm = None  # deterministic: no LLM in the eval gate
        return agent

    analysis_mod = _load("analysis_agent.py", "optgate_analysis_agent")
    sentiment_mod = _load("sentiment_agent.py", "optgate_sentiment_agent")
    risk_mod = _load("risk_agent.py", "optgate_risk_agent")
    synthesis_mod = _load("synthesis_agent.py", "optgate_synthesis_agent")
    decision_mod = _load("decision_agent.py", "optgate_decision_agent")
    report_mod = _load("report_agent.py", "optgate_report_agent")

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
# Scenario A — complacency 自满 (QVIX percentile <= 0.20)
# ---------------------------------------------------------------------------


class TestComplacencyScenario:
    async def test_snapshot_reaches_report_risk_section(self):
        state = _cn_state()
        state["option_snapshot"] = _option_snapshot(percentile=0.10, current=14.85)
        state, report = await _run_pipeline(state)
        result = _grade(state, report)
        assert result.passed, result.summary()

        block = report["sections"]["risk_analysis"]["option_implied"]
        assert block["status"] == "ok"
        assert block["regime"] == "自满"
        assert block["qvix"]["percentile_1y"] == 0.10
        # The full pipeline-nested shape survives the wire, not just a label.
        assert isinstance(block["iv"], dict) and block["iv"]["atm_iv_near"] is not None
        assert block["pcr"]["market_pcr"] == pytest.approx(
            (900_000.0 + 2_200_000.0) / (1_000_000.0 + 2_000_000.0)
        )

    async def test_buy_carries_complacency_warning(self):
        state = _cn_state()
        state["option_snapshot"] = _option_snapshot(percentile=0.10, current=14.85)
        state, report = await _run_pipeline(state)

        decision = state["decision"]["decisions"][CN]
        assert decision["action"] == "buy", "fixture must land in the buy band (non-vacuous gate)"
        assert any("complacent" in w and "QVIX" in w for w in decision["warnings"]), decision[
            "warnings"
        ]

        rec = report["sections"]["recommendations"]["by_symbol"][CN]
        assert rec["action"] == "buy"
        assert any("complacent" in w and "QVIX" in w for w in rec.get("warnings") or [])


# ---------------------------------------------------------------------------
# Scenario B — panic 恐慌 (QVIX percentile >= 0.80)
# ---------------------------------------------------------------------------


class TestPanicScenario:
    async def test_snapshot_reaches_report_risk_section(self):
        state = _cn_state()
        state["option_snapshot"] = _option_snapshot(percentile=0.92, current=32.4)
        state, report = await _run_pipeline(state)
        result = _grade(state, report)
        assert result.passed, result.summary()

        block = report["sections"]["risk_analysis"]["option_implied"]
        assert block["status"] == "ok"
        assert block["regime"] == "恐慌"
        assert block["qvix"]["percentile_1y"] == 0.92
        assert isinstance(block["iv"], dict) and block["iv"]["atm_iv_near"] is not None

    async def test_buy_carries_panic_warning(self):
        state = _cn_state()
        state["option_snapshot"] = _option_snapshot(percentile=0.92, current=32.4)
        state, report = await _run_pipeline(state)

        decision = state["decision"]["decisions"][CN]
        assert decision["action"] == "buy", "fixture must land in the buy band (non-vacuous gate)"
        assert any("panic" in w and "QVIX" in w for w in decision["warnings"]), decision["warnings"]

        rec = report["sections"]["recommendations"]["by_symbol"][CN]
        assert any("panic" in w and "QVIX" in w for w in rec.get("warnings") or [])


# ---------------------------------------------------------------------------
# Pure-annotation pin — the arc's design red line
# ---------------------------------------------------------------------------


class TestPureAnnotationPin:
    async def test_without_snapshot_numbers_are_bit_identical(self):
        """The option block may only APPEND warnings. The identical state
        minus ``option_snapshot`` must produce decisions with bit-identical
        action/score/confidence — annotation never touches numbers."""
        with_snap = _cn_state()
        with_snap["option_snapshot"] = _option_snapshot(percentile=0.10, current=14.85)
        s_with, r_with = await _run_pipeline(with_snap)
        s_without, r_without = await _run_pipeline(_cn_state())

        d_with = s_with["decision"]["decisions"][CN]
        d_without = s_without["decision"]["decisions"][CN]
        assert d_with["action"] == d_without["action"]
        assert d_with["score"] == d_without["score"]  # ==, not approx: bit-identical
        assert d_with["confidence"] == d_without["confidence"]

        # The annotation's whole effect is the warning strings.
        assert any("complacent" in w for w in d_with["warnings"])
        assert not any("complacent" in w for w in d_without.get("warnings") or [])

        # Absence convention mirrors market_regime's: risk block key present
        # with None, and the report's risk section carries no option key.
        assert s_without["risk_assessment"]["option_implied"] is None
        assert "option_implied" not in r_without["sections"]["risk_analysis"]
        assert "option_implied" in r_with["sections"]["risk_analysis"]
