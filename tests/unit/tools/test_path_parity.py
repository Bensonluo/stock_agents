"""Path-parity tests: pipeline agents and ReAct tools must agree, bit for bit.

These exist because the two execution paths used to carry duplicated logic
that had drifted (different thresholds, different weights). After the
unification waves both sides delegate to the same canonical modules — these
tests pin that property so a future copy cannot drift silently again.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

from app.analysis.fundamental.scoring import analyze_fundamental_scoring
from app.analysis.sentiment import score_news
from app.tools.risk.assessment import assess_risk


def _load_agent_module(file_name: str, module_name: str) -> ModuleType:
    """Load an agent module with stubbed base/state (package-cycle guard)."""
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
        path = Path(__file__).parents[3] / "app" / "agents" / file_name
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


def _market_history(days: int = 300) -> dict[str, list]:
    rng = np.random.default_rng(11)
    closes = [100.0]
    for _ in range(days - 1):
        closes.append(max(1.0, closes[-1] * (1 + 0.001 + rng.normal(0, 0.012))))
    return {
        "dates": [d.isoformat() for d in pd.bdate_range("2024-01-01", periods=days)],
        "open": [closes[0]] + closes[:-1],
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
        "volume": [1_000_000.0] * days,
    }


def _financial() -> dict:
    return {
        "metrics": {
            "roe": 0.17, "roa": 0.07, "profit_margin": 0.19, "operating_margin": 0.22,
            "pe_ratio": 21.0, "pb_ratio": 3.4, "ps_ratio": 3.8, "trailing_eps": 5.9,
            "debt_to_equity": 0.9, "current_ratio": 1.5, "revenue_growth": 0.11,
            "earnings_growth": 0.08,
        },
        "income_statement": {
            "dates": ["2023-12-31", "2024-12-31"],
            "data": {"Total Revenue": [90.0, 100.0], "Gross Profit": [33.0, 38.0], "Net Income": [10.0, 12.0]},
        },
        "cash_flow": {
            "dates": ["2023-12-31", "2024-12-31"],
            "data": {"Operating Cash Flow": [15.0, 18.0], "Capital Expenditure": [-4.0, -5.0]},
        },
    }


class TestFundamentalParity:
    def test_agent_and_tool_score_identically(self) -> None:
        module = _load_agent_module("analysis_agent.py", "analysis_agent_parity")
        agent = module.FundamentalAnalysisAgent()
        fin, mkt = _financial(), {"current_price": 150.0}

        import asyncio

        via_agent = asyncio.run(agent._analyze_fundamentals("TEST", fin, mkt))
        via_tool = analyze_fundamental_scoring({"TEST": fin}, {"TEST": mkt})["TEST"]

        for key in ("profitability", "valuation", "financial_health", "growth", "overall_score"):
            assert via_agent[key] == via_tool[key], f"drift in {key}"
        assert via_agent["recommendation"] == via_tool["recommendation"]


class TestRiskParity:
    @pytest.mark.asyncio
    async def test_agent_and_tool_report_identical_metrics(self) -> None:
        module = _load_agent_module("risk_agent.py", "risk_agent_parity")
        agent = module.RiskAssessmentAgent()
        history = _market_history()
        benchmark = {**history, "close": [c * 0.85 for c in history["close"]]}
        data = {
            "symbol": "TEST",
            "historical_data": history,
            "benchmark_historical_data": benchmark,
        }

        via_agent = await agent._assess_risk("TEST", data)
        via_tool = assess_risk.invoke({"market_data": {"TEST": data}})["TEST"]

        assert via_agent == via_tool


class TestSentimentParity:
    @pytest.mark.asyncio
    async def test_agent_and_tool_score_identically(self) -> None:
        module = _load_agent_module("sentiment_agent.py", "sentiment_agent_parity")
        agent = module.SentimentAnalysisAgent()
        news = [
            {"title": "Strong profit beat and record growth", "summary": "surge in demand", "related_symbols": ["TEST"]},
            {"title": "Lawsuit risk over debt", "summary": "downgrade warning", "related_symbols": ["TEST"]},
            {"title": "Neutral announcement", "summary": "", "related_symbols": ["TEST"]},
        ]

        via_agent = await agent._analyze_news_sentiment(news)
        via_tool = score_news(news)

        assert via_agent == via_tool


class TestDecisionParity:
    def test_pipeline_decision_matches_the_single_formula(self) -> None:
        module = _load_agent_module("decision_agent.py", "decision_agent_parity")
        agent = module.DecisionMakingAgent()
        from app.services.report_service import derive_recommendation

        technical = {"signals": {"trend": "bullish"}, "sentiment": {"score": 35}}
        fundamental = analyze_fundamental_scoring({"TEST": _financial()}, {"TEST": {"current_price": 150.0}})["TEST"]
        sentiment = {"sentiment": "positive", "score": 22}
        risk = {"risk_level": "medium", "position_recommendation": {"max_position_size": 10}}

        import asyncio

        decision = asyncio.run(
            agent._make_decision("TEST", technical, fundamental, sentiment, risk)
        )
        canonical = derive_recommendation("TEST", fundamental, technical, sentiment, risk)

        assert decision["action"] == canonical["action"]
        assert decision["confidence"] == canonical["confidence"]
        assert decision["score"] == canonical["composite_score"]
