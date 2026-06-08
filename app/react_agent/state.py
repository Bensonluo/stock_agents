"""ReAct agent state management."""

from typing import Annotated, Any, List, Optional

from langchain_core.messages import BaseMessage
from typing_extensions import TypedDict

from app.config import settings


def add_messages(left: list, right: list) -> list:
    return left + right


def add_items(left: list, right: list) -> list:
    return left + right


def merge_dicts(left: dict | None, right: dict | None) -> dict:
    """Deep merge: nested dicts merge recursively, leaves overwrite. None-safe.

    Used for `tool_results` so that a node returning a partial update
    (e.g. `{"analyze_technical": {"AAPL": {...}}}`) merges with the existing
    accumulated state without dropping earlier tool calls.
    """
    result = dict(left or {})
    for k, v in (right or {}).items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = merge_dicts(result[k], v)
        else:
            result[k] = v
    return result


class ReActState(TypedDict):
    """State for the ReAct autonomous agent."""

    # Original AgentState fields (backward compatibility)
    query: str
    symbols: List[str]
    thread_id: Optional[str]
    market_data: dict
    financial_data: dict
    news_data: List[dict]
    technical_analysis: dict
    fundamental_analysis: dict
    sentiment_analysis: dict
    risk_assessment: dict
    decision: dict
    report: Optional[dict]
    agent_outputs: Annotated[List[dict], add_items]
    errors: Annotated[List[dict], add_items]
    retry_count: int
    agent_status: dict
    execution_metadata: dict
    current_agent: str
    current_step: int
    max_retries: int
    timeout_per_agent: int
    parallel_execution: bool

    # ReAct fields
    messages: Annotated[List[BaseMessage], add_messages]
    iteration: int
    max_iterations: int
    tools_used: Annotated[List[str], add_items]
    tool_call_history: Annotated[List[dict], add_items]
    tool_results: Annotated[dict, merge_dicts]
    final_answer: Optional[str]
    accumulated_cost: float
    accumulated_tokens: dict


def create_initial_react_state(
    query: str,
    symbols: list[str],
    thread_id: str,
    max_iterations: Optional[int] = None,
) -> dict[str, Any]:
    from app.react_agent.prompts import PROMPT_VERSION

    return {
        "query": query,
        "symbols": symbols,
        "thread_id": thread_id,
        "messages": [],
        "iteration": 0,
        "max_iterations": max_iterations or settings.agent_max_iterations,
        "tools_used": [],
        "tool_call_history": [],
        "tool_results": {},
        "market_data": {},
        "financial_data": {},
        "news_data": [],
        "technical_analysis": {},
        "fundamental_analysis": {},
        "sentiment_analysis": {},
        "risk_assessment": {},
        "decision": {},
        "report": None,
        "final_answer": None,
        "accumulated_cost": 0.0,
        "accumulated_tokens": {"input": 0, "output": 0},
        "agent_outputs": [],
        "errors": [],
        "retry_count": 0,
        "agent_status": {},
        "execution_metadata": {"prompt_version": PROMPT_VERSION},
        "current_agent": "",
        "current_step": 0,
        "max_retries": settings.max_retries,
        "timeout_per_agent": settings.timeout_per_agent,
        "parallel_execution": settings.parallel_execution,
    }
