import pytest
from typing import get_type_hints
from app.react_agent.state import ReActState
from app.orchestration.state import AgentState


def test_react_state_has_all_agent_state_fields():
    """ReActState must include all AgentState fields (backward compatibility)."""
    agent_fields = set(AgentState.__annotations__.keys())
    react_fields = set(ReActState.__annotations__.keys())

    assert agent_fields.issubset(react_fields), (
        f"Missing fields: {agent_fields - react_fields}"
    )


def test_react_state_has_new_fields():
    """ReActState must have new ReAct-specific fields."""
    fields = ReActState.__annotations__

    assert "messages" in fields
    assert "iteration" in fields
    assert "max_iterations" in fields
    assert "tools_used" in fields
    assert "tool_call_history" in fields
    assert "final_answer" in fields
    assert "accumulated_cost" in fields
    assert "accumulated_tokens" in fields


def test_create_initial_react_state():
    """Test creating initial state with helper."""
    from app.react_agent.state import create_initial_react_state

    state = create_initial_react_state(
        query="Should I buy AAPL?",
        symbols=["AAPL"],
        thread_id="test-123",
    )

    assert state["query"] == "Should I buy AAPL?"
    assert state["symbols"] == ["AAPL"]
    assert state["thread_id"] == "test-123"
    assert state["iteration"] == 0
    assert state["max_iterations"] == 15
    assert state["messages"] == []
    assert state["tools_used"] == []
    assert state["tool_call_history"] == []
    assert state["final_answer"] is None
    assert state["accumulated_cost"] == 0.0
    assert state["accumulated_tokens"] == {"input": 0, "output": 0}
    assert "execution_metadata" in state
    assert state["execution_metadata"]["prompt_version"] is not None
