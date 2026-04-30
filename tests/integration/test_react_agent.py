import pytest
from unittest.mock import MagicMock, patch


@pytest.mark.asyncio
async def test_react_agent_with_mock_llm():
    """Test the full ReAct loop with a mock LLM."""
    from app.react_agent.react_agent import ReActAgent
    from app.react_agent.state import create_initial_react_state

    agent = ReActAgent()

    # Mock the LLM to simulate a simple tool call then finish
    mock_llm = MagicMock()

    # First call: tool call (fetch_stock_data)
    mock_response_1 = MagicMock()
    mock_response_1.tool_calls = [{
        "name": "fetch_stock_data",
        "args": {"symbols": ["AAPL"]},
        "id": "call_1",
    }]

    # Second call: finish (no tool calls)
    mock_response_2 = MagicMock()
    mock_response_2.tool_calls = []
    mock_response_2.content = "Based on the data, AAPL looks like a strong buy."

    mock_llm.bind_tools.return_value.invoke.side_effect = [mock_response_1, mock_response_2]

    mock_reflect_llm = MagicMock()
    mock_reflect_llm.invoke.return_value = MagicMock(content='{"decision": "finish"}')

    with patch("app.react_agent.react_agent._get_reasoning_llm", return_value=mock_llm), \
         patch("app.react_agent.react_agent._get_reflection_llm", return_value=mock_reflect_llm):
        state = create_initial_react_state(
            query="Should I buy AAPL?",
            symbols=["AAPL"],
            thread_id="test-123",
        )

        # Mock tool execution to avoid real API calls
        with patch("app.react_agent.react_agent.get_tool") as mock_get_tool:
            mock_tool = MagicMock()
            mock_tool.invoke.return_value = {"AAPL": {"market_data": {"current_price": 150.0}}}
            mock_get_tool.return_value = mock_tool

            result = await agent.graph.ainvoke(state)

    assert result["iteration"] > 0


def test_max_iteration_guard():
    """Test that the agent stops at max iterations."""
    from app.react_agent.react_agent import _reflect_decision

    state = {"iteration": 15, "max_iterations": 15, "final_answer": None}
    assert _reflect_decision(state) == "__end__"

    state = {"iteration": 14, "max_iterations": 15, "final_answer": None}
    assert _reflect_decision(state) == "agent_reason"


def test_repetition_detection():
    """Test that repeated tool calls force finish."""
    from app.react_agent.react_agent import reflect_node

    # Mock messages with repeated tool calls
    mock_msg = MagicMock()
    mock_msg.tool_calls = [{"name": "fetch_stock_data", "args": {"symbols": ["AAPL"]}}]

    state = {
        "iteration": 3,
        "max_iterations": 15,
        "tools_used": ["fetch_stock_data"],
        "query": "test",
        "messages": [mock_msg, mock_msg],  # Same tool call twice
    }

    result = reflect_node(state)

    # Should force finish by returning a guidance message
    assert "messages" in result
