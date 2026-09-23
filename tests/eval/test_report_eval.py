"""Eval harness: report-quality regression gate across scenarios.

Reuses the synthetic-data pipeline runner from test_pipeline_flow and grades
every scenario's report with the deterministic rubric. The gate is
all-or-nothing per scenario; assertion messages carry the per-check
breakdown so a regression shows WHICH invariant broke.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.eval.rubric import grade_report
from tests.integration.test_pipeline_flow import _load, _synthetic_state

pytestmark = pytest.mark.asyncio


async def _run_pipeline(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    def make(module, cls_name):
        agent = getattr(module, cls_name)()
        agent.llm = None  # deterministic: no LLM in the eval gate
        return agent

    analysis_mod = _load("analysis_agent.py", "eval_analysis_agent")
    sentiment_mod = _load("sentiment_agent.py", "eval_sentiment_agent")
    risk_mod = _load("risk_agent.py", "eval_risk_agent")
    synthesis_mod = _load("synthesis_agent.py", "eval_synthesis_agent")
    decision_mod = _load("decision_agent.py", "eval_decision_agent")
    report_mod = _load("report_agent.py", "eval_report_agent")

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


class TestScenarioEvals:
    async def test_happy_path_full_score(self):
        state, report = await _run_pipeline(_synthetic_state())
        result = _grade(state, report)
        assert result.passed, result.summary()
        assert result.score == 1.0

    async def test_flat_market_degrades_gracefully(self):
        state = _synthetic_state()
        for symbol in ("TEST",):
            hist = state["market_data"][symbol]["historical_data"]
            for key in ("open", "high", "low", "close"):
                hist[key] = [150.0] * len(hist["dates"])
        state, report = await _run_pipeline(state)
        result = _grade(state, report)
        assert result.passed, result.summary()

    async def test_deep_drawdown_degrades_gracefully(self):
        state = _synthetic_state()
        for symbol in ("TEST",):
            hist = state["market_data"][symbol]["historical_data"]
            days = len(hist["dates"])
            closes = [max(1.0, 200.0 * (0.995**i)) for i in range(days)]
            hist["close"] = closes
            hist["open"] = [closes[0]] + closes[:-1]
            hist["high"] = [c * 1.005 for c in closes]
            hist["low"] = [c * 0.995 for c in closes]
        state, report = await _run_pipeline(state)
        result = _grade(state, report)
        assert result.passed, result.summary()

    async def test_missing_financials_degrades_gracefully(self):
        state = _synthetic_state()
        state["financial_data"] = {}
        state, report = await _run_pipeline(state)
        result = _grade(state, report)
        assert result.passed, result.summary()

    async def test_multi_symbol_mixed_regimes(self):
        """3-symbol fan-out: uptrend + flat + deep drawdown in one run.

        Exercises the per-symbol paths inside every agent plus the rubric's
        cross-symbol coverage checks (decisions/evidence must cover all 3)."""
        symbols = ("UPTREND", "FLATCO", "DRAWDN")
        state = _synthetic_state("UPTREND", seed=5)
        for sym, seed in (("FLATCO", 6), ("DRAWDN", 7)):
            extra = _synthetic_state(sym, seed=seed)
            state["market_data"][sym] = extra["market_data"][sym]
            state["financial_data"][sym] = extra["financial_data"][sym]
            state["news_data"].extend(extra["news_data"])

        flat = state["market_data"]["FLATCO"]["historical_data"]
        for key in ("open", "high", "low", "close"):
            flat[key] = [150.0] * len(flat["dates"])

        down = state["market_data"]["DRAWDN"]["historical_data"]
        days = len(down["dates"])
        closes = [max(1.0, 200.0 * (0.995**i)) for i in range(days)]
        down["close"] = closes
        down["open"] = [closes[0]] + closes[:-1]
        down["high"] = [c * 1.005 for c in closes]
        down["low"] = [c * 0.995 for c in closes]

        state["symbols"] = list(symbols)
        state["query"] = "Analyze " + ", ".join(symbols)

        state, report = await _run_pipeline(state)
        result = _grade(state, report)
        assert result.passed, result.summary()
        assert set(state["decision"]["decisions"]) == set(symbols)

    async def test_ashare_akshare_shaped_data_degrades_gracefully(self):
        """CN symbols arrive via AkShare with a much thinner payload: no
        historical_data/benchmark, renamed financial metrics (net_margin,
        debt_to_asset), no income statement or cash flow. The pipeline must
        still produce a schema-compliant report covering both symbols."""
        state = _synthetic_state("TEST", seed=5)
        cn = "600519"
        state["symbols"] = ["TEST", cn]
        state["query"] = f"Analyze TEST, {cn}"
        state["market_data"][cn] = {
            "symbol": cn,
            "current_price": 1650.0,
            "change": 1.2,
            "change_percent": 1.2,
            "volume": 2_500_000,
            "amount": 4.1e9,
            "amplitude": 2.1,
            "high": 1660.0,
            "low": 1635.0,
            "open": 1640.0,
            "previous_close": 1630.0,
            "timestamp": "2026-09-24T10:00:00",
        }
        state["financial_data"][cn] = {
            "symbol": cn,
            "metrics": {
                "roe": 0.31,
                "roa": 0.19,
                "gross_margin": 0.91,
                "net_margin": 0.49,
                "debt_to_asset": 0.21,
                "current_ratio": 4.2,
                "quick_ratio": 3.9,
            },
            "timestamp": "2026-09-24T10:00:00",
        }

        state, report = await _run_pipeline(state)
        result = _grade(state, report)
        assert result.passed, result.summary()
        assert cn in state["decision"]["decisions"]


class TestRubricUnit:
    async def test_bad_report_fails_with_breakdown(self):
        result = grade_report({"title": "", "sections": {}}, decisions={}, symbols=["TEST"])
        assert not result.passed
        assert result.score < 1.0
        assert result.failures()

    async def test_non_dict_report_short_circuits(self):
        result = grade_report(None, decisions={}, symbols=[])
        assert not result.passed
        assert result.score == 0.0

    async def test_invalid_decision_action_flagged(self):
        report = {
            "title": "t",
            "executive_summary": "s",
            "sections": {
                k: {}
                for k in (
                    "overview",
                    "technical_analysis",
                    "fundamental_analysis",
                    "sentiment_analysis",
                    "risk_analysis",
                    "recommendations",
                    "research_synthesis",
                    "evidence_index",
                )
            },
        }
        result = grade_report(
            report,
            decisions={"TEST": {"action": "yolo", "confidence": 50}},
            symbols=["TEST"],
        )
        assert not result.passed
        assert any(name == "decision.action_enum" for name, _, _ in result.checks)


class TestLlmJudge:
    async def test_disabled_by_default_returns_none(self):
        from app.eval import judge

        assert await judge.judge_report("anything") is None

    async def test_enabled_routes_through_ainvoke_json(self, monkeypatch):
        from app.config import settings
        from app.eval import judge as judge_mod

        monkeypatch.setattr(settings, "eval_llm_judge", True)
        monkeypatch.setattr(settings, "zhipuai_api_key", "test-key")

        calls = {}

        async def _fake_ainvoke_json(llm, *, system, user, schema=None):
            calls["user"] = user
            return {
                "completeness": 8,
                "groundedness": 7,
                "actionability": 6,
                "risk_awareness": 9,
                "overall": 7,
                "rationale": "solid",
            }

        monkeypatch.setattr(judge_mod, "ainvoke_json", _fake_ainvoke_json)
        verdict = await judge_mod.judge_report("REPORT BODY")

        assert verdict is not None
        assert verdict["overall"] == 7
        assert "REPORT BODY" in calls["user"]

    async def test_unparsable_judge_degrades_to_none(self, monkeypatch):
        from app.config import settings
        from app.eval import judge as judge_mod

        monkeypatch.setattr(settings, "eval_llm_judge", True)
        monkeypatch.setattr(settings, "zhipuai_api_key", "test-key")

        async def _broken(llm, *, system, user, schema=None):
            return None

        monkeypatch.setattr(judge_mod, "ainvoke_json", _broken)
        assert await judge_mod.judge_report("x") is None
