"""Prompt currency: the system prompt must describe the registry as it is.

The registry (register_all_tools) and REASONING_SYSTEM_PROMPT drifted twice:
analyze_valuation was registered but never listed (invisible to the LLM), and
calculate_position_size's entry omitted technical_data — so ATR volatility
sizing could never fire on the ReAct path. The registry-coverage test below
makes that drift structurally impossible: adding a tool without teaching the
prompt about it fails the suite.
"""

from __future__ import annotations

import pytest

from app.react_agent import prompts
from app.tools import get_all_tools, register_all_tools


@pytest.fixture(autouse=True)
def _registered_tools():
    register_all_tools()


class TestRegistryCoverage:
    def test_every_registered_tool_appears_in_the_prompt(self) -> None:
        registered = sorted(tool.name for tool in get_all_tools())
        assert registered, "registry came up empty — registration is broken"

        missing = [name for name in registered if name not in prompts.REASONING_SYSTEM_PROMPT]
        assert not missing, (
            f"Registered tools the LLM has never been told about: {missing}. "
            "Add them to AVAILABLE TOOLS in REASONING_SYSTEM_PROMPT."
        )

    def test_registry_has_the_full_tenant_toolset(self) -> None:
        # Guard against the opposite drift: the prompt listing tools that were
        # removed from the registry. Ten names as of iteration 63.
        assert sorted(tool.name for tool in get_all_tools()) == [
            "analyze_fundamental",
            "analyze_sentiment",
            "analyze_technical",
            "analyze_valuation",
            "assess_risk",
            "calculate_position_size",
            "fetch_stock_data_tool",
            "generate_report",
            "get_historical_prices",
            "get_stock_overview",
        ]


class TestReportDataWiring:
    @staticmethod
    def _state(tool_results: dict) -> dict:
        return {"query": "analyze", "symbols": ["AAPL"], "tool_results": tool_results}

    def test_fetch_results_reach_report_data_under_the_real_tool_name(self) -> None:
        # The executor indexes tool_results by the tool name the LLM called
        # (fetch_stock_data_tool); _build_report_data used to read the
        # nonexistent "fetch_stock_data" key, so the fetch tool's payload
        # never reached generate_report directly.
        from app.react_agent.react_agent import _build_report_data

        tr = {
            "fetch_stock_data_tool": {
                "AAPL": {
                    "market_data": {"symbol": "AAPL", "current_price": 190.0},
                    "financial_data": {"symbol": "AAPL", "metrics": {}},
                    "news_data": [{"title": "t"}],
                }
            }
        }

        data = _build_report_data(self._state(tr))

        assert data["market_data"]["AAPL"]["current_price"] == 190.0
        assert "AAPL" in data["financial_data"]
        assert data["news_data"] == [{"title": "t"}]

    def test_missing_fetch_bucket_still_degrades(self) -> None:
        # The reconstruction fallback remains for runs where the fetch tool
        # genuinely failed; absent key must not KeyError.
        from app.react_agent.react_agent import _build_report_data

        data = _build_report_data(self._state({}))
        assert "market_data" not in data


class TestSizingWorkflow:
    def test_prompt_teaches_the_technical_data_contract(self) -> None:
        # calculate_position_size only does ATR sizing when technical_data is
        # populated per symbol; the prompt must teach that nesting explicitly.
        text = prompts.REASONING_SYSTEM_PROMPT
        assert "technical_data" in text
        assert "risk_data" in text

    def test_valuation_tool_is_visible(self) -> None:
        # The iteration-63 finding: registered but absent from AVAILABLE TOOLS.
        assert "analyze_valuation:" in prompts.REASONING_SYSTEM_PROMPT


class TestDeadCodeStaysDeleted:
    def test_reflection_prompt_template_gone(self) -> None:
        # Iteration 9b removed the LLM reflection path; these were orphans.
        assert not hasattr(prompts, "REFLECTION_PROMPT_TEMPLATE")
        assert not hasattr(prompts, "format_reflection_prompt")


class TestVersionBump:
    def test_prompt_version(self) -> None:
        assert prompts.PROMPT_VERSION == "1.2.0"
