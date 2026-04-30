"""ReAct agent state management.

ReActState is a standalone TypedDict that includes ALL fields from AgentState
plus new ReAct-specific fields. This ensures backward compatibility with the
existing checkpoint system and database serialization.
"""

from typing import Annotated, Any, List, Optional

from langchain_core.messages import BaseMessage
from typing_extensions import TypedDict

from app.config import settings


def add_messages(left: list, right: list) -> list:
    """Reducer for messages: append new messages."""
    return left + right


def add_items(left: list, right: list) -> list:
    """Reducer for lists: append items."""
    return left + right


class ReActState(TypedDict):
    """State for the ReAct autonomous agent.

    Includes all fields from the original AgentState for backward compatibility,
    plus new fields for the ReAct loop.
    """

    # --- Original AgentState fields (preserved for backward compatibility) ---
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

    # --- New ReAct fields ---
    messages: Annotated[List[BaseMessage], add_messages]
    iteration: int
    max_iterations: int
    tools_used: Annotated[List[str], add_items]
    tool_call_history: Annotated[List[dict], add_items]
    final_answer: Optional[str]
    accumulated_cost: float
    accumulated_tokens: dict


def create_initial_react_state(
    query: str,
    symbols: list[str],
    thread_id: str,
    max_iterations: Optional[int] = None,
) -> dict[str, Any]:
    """Create initial ReAct state.

    Args:
        query: User query
        symbols: Stock symbols to analyze
        thread_id: Unique thread identifier
        max_iterations: Maximum ReAct iterations (defaults to config)

    Returns:
        Initial state dictionary matching ReActState
    """
    from app.react_agent.prompts import PROMPT_VERSION

    return {
        # Input
        "query": query,
        "symbols": symbols,
        "thread_id": thread_id,
        # ReAct Loop
        "messages": [],
        "iteration": 0,
        "max_iterations": max_iterations or settings.agent_max_iterations,
        # Tool tracking
        "tools_used": [],
        "tool_call_history": [],
        # Collected data (original AgentState fields)
        "market_data": {},
        "financial_data": {},
        "news_data": [],
        "technical_analysis": {},
        "fundamental_analysis": {},
        "sentiment_analysis": {},
        "risk_assessment": {},
        "decision": {},
        "report": None,
        # Final output
        "final_answer": None,
        # Cost tracking
        "accumulated_cost": 0.0,
        "accumulated_tokens": {"input": 0, "output": 0},
        # Execution tracking (original AgentState fields)
        "agent_outputs": [],
        "errors": [],
        "retry_count": 0,
        "agent_status": {},
        "execution_metadata": {
            "prompt_version": PROMPT_VERSION,
        },
        "current_agent": "",
        "current_step": 0,
        "max_retries": settings.max_retries,
        "timeout_per_agent": settings.timeout_per_agent,
        "parallel_execution": settings.parallel_execution,
    }
