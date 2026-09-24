"""Offline CI test: the LLM judge grades a REAL deterministic pipeline report.

test_judge_wire.py proves the SDK/HTTP wire with a canned string, and
test_report_eval.py's judge tests feed canned strings too. Neither proves
that a report actually produced by the agent pipeline survives rendering
and reaches the judge prompt. This file closes that gap: it runs the full
agent chain over synthetic data with no LLM, serializes the report the
same way app/eval/rubric.py does (json.dumps with default=str), and pushes
it through judge_report over httpx.MockTransport — proving real pipeline
output travels to the judge endpoint and parses back into a verdict, and
that a garbage judge reply still degrades to None instead of raising.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.eval import judge as judge_mod
from tests.eval.test_judge_wire import _enable_judge, _install_transport, _Recorder
from tests.integration.test_pipeline_flow import _load, _synthetic_state

pytestmark = pytest.mark.asyncio


async def _run_pipeline(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Deterministic agent chain, orchestrator order, no LLM (eval gate)."""

    def make(module, cls_name):
        agent = getattr(module, cls_name)()
        agent.llm = None  # deterministic: no LLM in the eval gate
        return agent

    analysis_mod = _load("analysis_agent.py", "scenario_analysis_agent")
    sentiment_mod = _load("sentiment_agent.py", "scenario_sentiment_agent")
    risk_mod = _load("risk_agent.py", "scenario_risk_agent")
    synthesis_mod = _load("synthesis_agent.py", "scenario_synthesis_agent")
    decision_mod = _load("decision_agent.py", "scenario_decision_agent")
    report_mod = _load("report_agent.py", "scenario_report_agent")

    state.update(await make(analysis_mod, "TechnicalAnalysisAgent").execute(state))
    state.update(await make(analysis_mod, "FundamentalAnalysisAgent").execute(state))
    state["sentiment_analysis"] = await make(sentiment_mod, "SentimentAnalysisAgent").process(state)
    state["risk_assessment"] = await make(risk_mod, "RiskAssessmentAgent").process(state)
    state.update(await make(synthesis_mod, "ResearchSynthesisAgent").process(state))
    state["decision"] = await make(decision_mod, "DecisionMakingAgent").process(state)
    return state, await make(report_mod, "ReportGenerationAgent").process(state)


class TestJudgeOverRealPipelineReport:
    async def test_real_pipeline_report_round_trips_through_judge(self, monkeypatch):
        """A pipeline-rendered report reaches the judge prompt and the mocked
        completion parses back into a matching verdict."""
        reply = json.dumps(
            {
                "completeness": 8,
                "groundedness": 7,
                "actionability": 6,
                "risk_awareness": 9,
                "overall": 7,
                "rationale": "solid, evidence-tied",
            }
        )
        recorder = _Recorder(content=reply)
        _install_transport(monkeypatch, recorder)
        _enable_judge(monkeypatch)

        state, report = await _run_pipeline(_synthetic_state())
        text = json.dumps(report, ensure_ascii=False, default=str)
        assert len(text) > 0

        verdict = await judge_mod.judge_report(text)

        assert verdict is not None
        assert verdict["completeness"] == 8
        assert verdict["groundedness"] == 7
        assert verdict["actionability"] == 6
        assert verdict["risk_awareness"] == 9
        assert verdict["overall"] == 7
        assert verdict["rationale"] == "solid, evidence-tied"

        assert recorder.requests, "judge made no HTTP request at all"
        request = recorder.requests[0]
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["Authorization"] == "Bearer test-key"
        # Real pipeline data traveled to the judge: the deterministic report
        # title leads the serialized payload (title is the report's first key),
        # safely inside the 12000-char truncation and quote-free on the wire.
        assert b"Investment Research Report: TEST" in request.read()

    async def test_garbage_judge_reply_degrades_to_none_on_real_report(self, monkeypatch):
        """Same real input, unparsable judge reply: degrade, don't raise."""
        recorder = _Recorder(content="cannot grade this")
        _install_transport(monkeypatch, recorder)
        _enable_judge(monkeypatch)

        state, report = await _run_pipeline(_synthetic_state())
        text = json.dumps(report, ensure_ascii=False, default=str)
        assert len(text) > 0

        assert await judge_mod.judge_report(text) is None
        assert recorder.requests  # genuinely asked, not short-circuited
