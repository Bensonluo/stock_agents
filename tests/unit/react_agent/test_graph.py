import pytest


def test_build_react_graph_returns_callable():
    """The graph builder must return a compiled graph."""
    from app.react_agent.react_agent import build_react_graph

    graph = build_react_graph()
    assert callable(graph.ainvoke)


def test_agent_reason_decision_routing():
    """agent_reason must route to tool_execute or finish."""
    from app.react_agent.react_agent import _agent_reason_decision

    # State with no tool calls -> finish
    from langchain_core.messages import AIMessage
    state_no_tools = {"messages": [AIMessage(content="Done")]}
    assert _agent_reason_decision(state_no_tools) == "__end__"


def test_reflect_decision_max_iterations():
    """reflect must finish when max iterations reached."""
    from app.react_agent.react_agent import _reflect_decision

    state = {"iteration": 15, "max_iterations": 15, "final_answer": None}
    assert _reflect_decision(state) == "__end__"

    state = {"iteration": 14, "max_iterations": 15, "final_answer": None}
    assert _reflect_decision(state) == "agent_reason"


def test_reflect_decision_with_final_answer():
    """reflect must finish if final_answer is set."""
    from app.react_agent.react_agent import _reflect_decision

    state = {"iteration": 5, "max_iterations": 15, "final_answer": "Buy AAPL"}
    assert _reflect_decision(state) == "__end__"
