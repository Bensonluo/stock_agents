"""Integration tests: weekly SMA engine wired into agents, tools and reports."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest

from app.analysis.technical import (
    compact_weekly_view,
    weekly_sma_pack,
    weekly_sma_summary,
)


def _uptrend_daily(days: int = 800, *, ohlcv: bool = False, start: str = "2023-08-01") -> dict[str, list]:
    """Rising business-day closes; optional full OHLCV for the pipeline agent."""
    closes = [100.0 * (1.002**i) for i in range(days)]
    history: dict[str, list] = {
        "dates": [d.isoformat() for d in pd.bdate_range(start, periods=days)],
        "close": closes,
        "volume": [1_000_000.0] * days,
    }
    if ohlcv:
        history |= {"open": closes, "high": closes, "low": closes}
    return history


def _load_agent_class(module_name: str, file_name: str, class_name: str) -> type:
    """Load an agent module with stubbed base/state modules (avoids package cycle)."""
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
        module_path = Path(__file__).parents[3] / "app" / "agents" / file_name
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return getattr(module, class_name)
    finally:
        for name, original in replaced.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


TechnicalAnalysisAgent = _load_agent_class(
    "analysis_agent_under_test", "analysis_agent.py", "TechnicalAnalysisAgent"
)
ReportGenerationAgent = _load_agent_class(
    "report_agent_under_test", "report_agent.py", "ReportGenerationAgent"
)


class TestCompactWeeklyView:
    def test_unavailable_inputs_are_flagged_not_crashed(self) -> None:
        for pack in (None, {}, {"status": "error", "reason": "boom"}):
            assert compact_weekly_view(pack) == {"status": "unavailable"}

    def test_insufficient_data_passes_reason_through(self) -> None:
        pack = weekly_sma_pack({"dates": [], "close": []}, symbol="AAPL")

        view = compact_weekly_view(pack)

        assert view["status"] == "insufficient_data"
        assert view["reason"]

    def test_available_pack_shows_alignment_and_distances(self) -> None:
        pack = weekly_sma_pack(_uptrend_daily(), symbol="AAPL")

        view = compact_weekly_view(pack)

        assert view["status"] == "available"
        assert view["alignment"]["state"] == "bullish"
        assert view["alignment"]["weeks_in_state"] >= 1
        assert all(distance > 0 for distance in view["sma_distance_pct"].values())
        assert "recent_crosses" not in view

    def test_reversal_pack_reports_recent_crosses(self) -> None:
        closes = [200.0 * (0.995**i) for i in range(110 * 5)]
        trough = closes[-1]
        closes += [trough * (1.006**i) for i in range(30 * 5)]
        history = {
            "dates": [d.isoformat() for d in pd.bdate_range("2023-08-01", periods=len(closes))],
            "close": closes,
            "volume": [1_000_000.0] * len(closes),
        }
        pack = weekly_sma_pack(history, symbol="NVDA")

        view = compact_weekly_view(pack)

        assert any(
            cross["direction"] == "golden" for cross in view.get("recent_crosses", {}).values()
        )


class TestWeeklySmaSummary:
    def test_summary_is_json_serializable_with_and_without_evidence(self) -> None:
        history = _uptrend_daily()

        with_evidence = weekly_sma_summary(history, symbol="AAPL", source="test")
        without_evidence = weekly_sma_summary(history, symbol="AAPL", include_evidence=False)

        assert isinstance(with_evidence["evidence"][0], dict)
        assert isinstance(with_evidence["data_quality"], dict)
        assert "evidence" not in without_evidence
        assert without_evidence["alignment"]["state"] == "bullish"
        assert without_evidence["sma"]["20"]["value"] > 0


class TestPipelineAnalysisAgent:
    @pytest.mark.asyncio
    async def test_analyze_symbol_includes_weekly_sma_pack(self) -> None:
        agent = TechnicalAnalysisAgent()
        data = {
            "symbol": "AAPL",
            "current_price": 123.45,
            "historical_data": _uptrend_daily(ohlcv=True),
        }

        result = await agent._analyze_symbol("AAPL", data)

        assert result["symbol"] == "AAPL"
        weekly = result["weekly_sma"]
        assert weekly["status"] == "available"
        assert weekly["alignment"]["state"] == "bullish"
        assert weekly["sma"]["60"]["warm_up_met"] is True
        assert isinstance(weekly["evidence"], list)

    @pytest.mark.asyncio
    async def test_short_history_degrades_weekly_but_keeps_daily_analysis(self) -> None:
        agent = TechnicalAnalysisAgent()
        # 20 business days from a Monday = 4 weekly bars, below MIN_WEEKLY_BARS(5),
        # while the daily path still has enough rows for its own indicators.
        history = _uptrend_daily(days=20, ohlcv=True, start="2023-07-31")

        result = await agent._analyze_symbol("AAPL", {"historical_data": history})

        assert result["indicators"]  # daily analysis still produced output
        assert result["weekly_sma"]["status"] == "insufficient_data"
        assert result["weekly_sma"]["reason"]


class TestReportLayers:
    def test_report_agent_technical_section_carries_weekly_trend(self) -> None:
        agent = ReportGenerationAgent()
        pack = weekly_sma_pack(_uptrend_daily(), symbol="AAPL")
        data = {
            "technical_analysis": {
                "AAPL": {"signals": {"trend": "bullish"}, "sentiment": {"score": 40}, "weekly_sma": pack}
            }
        }

        section = agent._generate_technical_section(data)

        weekly = section["by_symbol"]["AAPL"]["weekly_trend"]
        assert weekly["alignment"]["state"] == "bullish"
        assert weekly["sma_distance_pct"]

    def test_report_agent_handles_missing_weekly_block(self) -> None:
        agent = ReportGenerationAgent()
        data = {"technical_analysis": {"AAPL": {"signals": {}, "sentiment": {"score": 0}}}}

        section = agent._generate_technical_section(data)

        assert section["by_symbol"]["AAPL"]["weekly_trend"] == {"status": "unavailable"}

    def test_generate_report_tool_carries_weekly_trend(self) -> None:
        from app.tools.report.generate import generate_report

        pack = weekly_sma_pack(_uptrend_daily(), symbol="MSFT")
        report = generate_report.invoke(
            {"data": {"technical_analysis": {"MSFT": {"signals": {"trend": "bullish"}, "weekly_sma": pack}}}}
        )

        weekly = report["sections"]["technical_analysis"]["by_symbol"]["MSFT"]["weekly_trend"]
        assert weekly["status"] == "available"
        assert weekly["alignment"]["state"] == "bullish"


class TestReActAutoTools:
    @pytest.mark.asyncio
    async def test_weekly_sma_helper_omits_evidence_for_llm_budget(self) -> None:
        from app.domain.schemas import DataQuality, QualityGateVerdict
        from app.tools.analysis.auto_tools import _weekly_sma

        result = _weekly_sma("AAPL", _uptrend_daily())

        assert result["status"] == "available"
        assert "evidence" not in result
        # data_quality round-trips through JSON and keeps its gate verdict
        restored = DataQuality.model_validate(result["data_quality"])
        assert restored.verdict is QualityGateVerdict.PASS
