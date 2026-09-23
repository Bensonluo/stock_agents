"""Functional test: the full pipeline sequence over synthetic data.

Runs the real agents in orchestrator order (technical -> fundamental ->
sentiment -> risk -> synthesis -> decision -> report) with no mocks inside
the chain — only the data layer is synthetic. This is the functional
guarantee that the assembled pipeline still produces a complete, JSON-safe
report after the unification waves.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd


def _load(file_name: str, module_name: str) -> ModuleType:
    base_module = ModuleType("app.agents.base")
    base_module.BaseAgent = type("BaseAgent", (), {})
    base_module.StatelessAgent = type("StatelessAgent", (), {})
    state_module = ModuleType("app.orchestration.state")
    state_module.AgentState = dict
    replaced = {
        name: sys.modules.get(name) for name in ("app.agents.base", "app.orchestration.state")
    }
    sys.modules.update({"app.agents.base": base_module, "app.orchestration.state": state_module})
    try:
        path = Path(__file__).parents[2] / "app" / "agents" / file_name
        spec = importlib.util.spec_from_file_location(module_name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, original in replaced.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


def _synthetic_state() -> dict[str, Any]:
    rng = np.random.default_rng(5)
    days = 800
    closes = [150.0]
    for _ in range(days - 1):
        closes.append(max(1.0, closes[-1] * (1 + 0.0008 + rng.normal(0, 0.011))))
    dates = [d.isoformat() for d in pd.bdate_range(end=date.today(), periods=days)]
    history = {
        "dates": dates,
        "open": [closes[0]] + closes[:-1],
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
        "volume": [1_000_000.0] * days,
    }
    benchmark = {**history, "close": [c * 0.92 for c in closes]}

    market = {
        "symbol": "TEST",
        "current_price": closes[-1],
        "change": 1.2,
        "change_percent": 0.8,
        "volume": 1_000_000,
        "market_cap": 2.5e12,
        "company_name": "Flow Test Inc",
        "sector": "Technology",
        "as_of": dates[-1],
        "historical_data": history,
        "benchmark_historical_data": benchmark,
    }
    financial = {
        "metrics": {
            "roe": 0.19,
            "roa": 0.08,
            "profit_margin": 0.21,
            "operating_margin": 0.26,
            "pe_ratio": 19.0,
            "pb_ratio": 3.1,
            "ps_ratio": 3.9,
            "trailing_eps": 6.2,
            "debt_to_equity": 0.7,
            "current_ratio": 1.7,
            "revenue_growth": 0.13,
            "earnings_growth": 0.09,
        },
        "income_statement": {
            "dates": ["2022-12-31", "2023-12-31", "2024-12-31"],
            "data": {
                "Total Revenue": [85.0, 100.0, 118.0],
                "Gross Profit": [32.0, 39.0, 48.0],
                "Net Income": [9.0, 12.0, 15.0],
            },
        },
        "cash_flow": {
            "dates": ["2023-12-31", "2024-12-31"],
            "data": {"Operating Cash Flow": [17.0, 22.0], "Capital Expenditure": [-5.0, -6.0]},
        },
    }
    news = [
        {
            "title": "Strong profit beat and record growth",
            "summary": "surge in demand",
            "related_symbols": ["TEST"],
        },
        {"title": "Neutral product announcement", "summary": "", "related_symbols": ["TEST"]},
    ]
    return {
        "query": "Analyze TEST",
        "symbols": ["TEST"],
        "market_data": {"TEST": market},
        "financial_data": {"TEST": financial},
        "news_data": news,
    }


def await_(coroutine: Any) -> Any:
    return asyncio.run(coroutine)


def test_pipeline_produces_complete_json_safe_report() -> None:
    analysis_mod = _load("analysis_agent.py", "flow_analysis_agent")
    sentiment_mod = _load("sentiment_agent.py", "flow_sentiment_agent")
    risk_mod = _load("risk_agent.py", "flow_risk_agent")
    synthesis_mod = _load("synthesis_agent.py", "flow_synthesis_agent")
    decision_mod = _load("decision_agent.py", "flow_decision_agent")
    report_mod = _load("report_agent.py", "flow_report_agent")

    def make(module, cls_name):
        agent = getattr(module, cls_name)()
        agent.llm = None  # stubbed base has no __init__; deterministic run
        return agent

    state = _synthetic_state()

    # Orchestrator order and state-key assignment semantics: analysis agents
    # return their partial state; stateless agents' results are assigned to
    # their node's state key by the orchestrator.
    state.update(asyncio.run(make(analysis_mod, "TechnicalAnalysisAgent").execute(state)))
    state.update(asyncio.run(make(analysis_mod, "FundamentalAnalysisAgent").execute(state)))
    state["sentiment_analysis"] = await_(
        make(sentiment_mod, "SentimentAnalysisAgent").process(state)
    )
    state["risk_assessment"] = await_(make(risk_mod, "RiskAssessmentAgent").process(state))
    state.update(await_(make(synthesis_mod, "ResearchSynthesisAgent").process(state)))
    state["decision"] = await_(make(decision_mod, "DecisionMakingAgent").process(state))
    report = await_(make(report_mod, "ReportGenerationAgent").process(state))

    # --- stage-level assertions ---
    tech = state["technical_analysis"]["TEST"]
    assert tech["weekly_sma"]["alignment"]["state"] in ("bullish", "bearish", "mixed")
    fund = state["fundamental_analysis"]["TEST"]
    assert fund["quality"]["status"] == "available"
    assert fund["valuation_scenarios"]["status"] == "available"
    risk = state["risk_assessment"]["risk_by_symbol"]["TEST"]
    assert risk["metrics"]["beta"] is not None
    assert risk["stress_scenarios"]["status"] == "available"

    synthesis = state["research_synthesis"]
    assert synthesis["audit"]["verdict"] == "pass"
    entry = synthesis["per_symbol"]["TEST"]
    assert entry["debate"]["bull_points"] or entry["debate"]["bear_points"]
    assert entry["committee"]["verdict"] in ("approve", "limit", "veto", "watch")

    decision = state["decision"]["decisions"]["TEST"]
    assert decision["action"] in ("buy", "add", "hold", "reduce", "sell")
    assert 0.0 <= decision["confidence"] <= 1.0  # derive_recommendation fraction

    # --- report-level assertions ---
    sections = report["sections"]
    for key in (
        "overview",
        "technical_analysis",
        "fundamental_analysis",
        "sentiment_analysis",
        "risk_analysis",
        "recommendations",
        "research_synthesis",
        "evidence_index",
    ):
        assert key in sections, f"missing report section {key}"
    assert sections["evidence_index"]["TEST"], "evidence drawer has no records"
    assert sections["research_synthesis"]["by_symbol"]["TEST"]["committee_verdict"]

    payload = json.dumps(report, ensure_ascii=False)  # raises on any leak
    assert len(payload) > 5000
