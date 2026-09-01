import json
from typing import Any

import pytest
from langchain_core.messages import ToolMessage

from app.react_agent.react_agent import ReActAgent, observe_node


def test_observe_node_preserves_structured_report() -> None:
    report = {
        "title": "Test report",
        "executive_summary": "Summary",
        "sections": {"overview": {"market_summary": {}}},
    }
    state = {
        "messages": [
            ToolMessage(
                content=json.dumps(report),
                tool_call_id="report-call",
                name="generate_report",
            )
        ],
        "tools_used": ["generate_report"],
    }

    result = observe_node(state)

    assert result["report"] == report
    assert "# Test report" in result["final_answer"]


@pytest.mark.asyncio
async def test_analyze_passes_requested_iteration_limit() -> None:
    captured_state: dict[str, Any] = {}

    class FakeGraph:
        async def astream(self, state: dict[str, Any]):
            captured_state.update(state)
            yield {"observe": {"final_answer": "done"}}

    agent = ReActAgent.__new__(ReActAgent)
    agent.graph = FakeGraph()

    result = await agent.analyze(
        query="Analyze TEST",
        symbols=["TEST"],
        thread_id="react-test",
        max_iterations=7,
    )

    assert captured_state["max_iterations"] == 7
    assert result["answer"] == "done"
