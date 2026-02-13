"""State management for multi-agent orchestration."""

from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional, Sequence

from langchain_core.messages import BaseMessage
from operator import add
from typing_extensions import TypedDict


class AgentState(TypedDict):
    """Global state definition - shared by all agents.

    This state follows immutability principles:
    - State updates produce new states, never modifying the original
    - All state is serializable for PostgreSQL checkpoint persistence
    - Uses TypedDict for type safety
    - Uses Annotated with add operator for list accumulation
    """

    # ========== Input Information ==========
    query: str  # User query
    symbols: List[str]  # Stock symbol list
    thread_id: Optional[str]  # Thread ID for workflow tracking

    # ========== Data State ==========
    market_data: Dict[str, Any]  # Market data
    financial_data: Dict[str, Any]  # Financial data
    news_data: List[Dict]  # News data

    # ========== Analysis Results ==========
    technical_analysis: Dict  # Technical analysis results
    fundamental_analysis: Dict  # Fundamental analysis results
    sentiment_analysis: Dict  # Sentiment analysis results

    # ========== Risk and Decision ==========
    risk_assessment: Dict  # Risk assessment
    decision: Dict  # Decision results

    # ========== Report ==========
    report: Dict  # Generated report

    # ========== Execution State (Core Learning Part) ==========
    agent_outputs: Annotated[List[Dict], add]  # Accumulated agent outputs
    errors: Annotated[List[Dict], add]  # Accumulated error list
    retry_count: Dict[str, int]  # Retry count per agent
    agent_status: Dict[str, str]  # Agent status
    execution_metadata: Dict  # Execution metadata

    # ========== Control Parameters ==========
    max_retries: int  # Max retry count
    timeout_per_agent: int  # Timeout per agent
    parallel_execution: bool  # Whether to execute in parallel

    # ========== Current Agent Tracking ==========
    current_agent: Optional[str]  # Currently executing agent
    current_step: int  # Current step number


def create_initial_state(
    query: str,
    symbols: List[str],
    thread_id: Optional[str] = None,
    max_retries: int = 3,
    timeout_per_agent: int = 300,
    parallel_execution: bool = True,
) -> AgentState:
    """Create an initial state for a new workflow execution.

    Args:
        query: User's query string
        symbols: List of stock symbols to analyze
        thread_id: Optional thread ID for workflow tracking
        max_retries: Maximum number of retries per agent
        timeout_per_agent: Timeout in seconds for each agent
        parallel_execution: Whether agents can execute in parallel

    Returns:
        A new AgentState instance with initial values
    """
    return AgentState(
        # Input
        query=query,
        symbols=symbols,
        thread_id=thread_id,
        # Data (empty initially)
        market_data={},
        financial_data={},
        news_data=[],
        # Analysis (empty initially)
        technical_analysis={},
        fundamental_analysis={},
        sentiment_analysis={},
        # Risk and decision (empty initially)
        risk_assessment={},
        decision={},
        # Report (empty initially)
        report={},
        # Execution state
        agent_outputs=[],
        errors=[],
        retry_count={},
        agent_status={},
        execution_metadata={
            "started_at": datetime.now(),
            "workflow_id": f"workflow-{datetime.now().timestamp()}",
        },
        # Control parameters
        max_retries=max_retries,
        timeout_per_agent=timeout_per_agent,
        parallel_execution=parallel_execution,
        # Current agent tracking
        current_agent=None,
        current_step=0,
    )


def update_state_immutable(state: AgentState, **updates: Any) -> AgentState:
    """Update state immutably by creating a new state.

    This function ensures that state updates follow immutability principles:
    - Always creates a new state dictionary
    - Never modifies the original state in place
    - Handles nested updates properly

    Args:
        state: Current state
        **updates: Key-value pairs to update

    Returns:
        A new state with updates applied
    """
    new_state = dict(state)

    for key, value in updates.items():
        if key in new_state and isinstance(new_state[key], dict) and isinstance(value, dict):
            # Merge dictionaries
            new_state[key] = {**new_state[key], **value}
        else:
            # Direct replacement
            new_state[key] = value

    return AgentState(**new_state)


def get_agent_status(state: AgentState, agent_name: str) -> str:
    """Get the status of a specific agent.

    Args:
        state: Current state
        agent_name: Name of the agent

    Returns:
        Agent status string (pending, running, completed, failed)
    """
    return state.get("agent_status", {}).get(agent_name, "pending")


def set_agent_status(state: AgentState, agent_name: str, status: str) -> AgentState:
    """Set the status of a specific agent immutably.

    Args:
        state: Current state
        agent_name: Name of the agent
        status: New status (pending, running, completed, failed)

    Returns:
        Updated state
    """
    agent_status = state.get("agent_status", {}).copy()
    agent_status[agent_name] = status
    return update_state_immutable(state, agent_status=agent_status)


def add_agent_output(
    state: AgentState, agent_name: str, result: Dict, metadata: Optional[Dict] = None
) -> AgentState:
    """Add an agent output to the state.

    Args:
        state: Current state
        agent_name: Name of the agent
        result: Result from the agent
        metadata: Optional metadata about the execution

    Returns:
        Updated state with new output appended
    """
    output = {
        "agent": agent_name,
        "result": result,
        "timestamp": datetime.now(),
        "metadata": metadata or {},
    }

    outputs = state.get("agent_outputs", []).copy()
    outputs.append(output)

    return update_state_immutable(state, agent_outputs=outputs)


def add_error(
    state: AgentState,
    agent_name: str,
    error_type: str,
    message: str,
    retryable: bool = False,
) -> AgentState:
    """Add an error to the state.

    Args:
        state: Current state
        agent_name: Name of the agent that encountered the error
        error_type: Type of error
        message: Error message
        retryable: Whether the error is retryable

    Returns:
        Updated state with new error appended
    """
    error = {
        "agent": agent_name,
        "type": error_type,
        "message": message,
        "timestamp": datetime.now(),
        "retryable": retryable,
    }

    errors = state.get("errors", []).copy()
    errors.append(error)

    # Increment retry count if retryable
    retry_count = state.get("retry_count", {}).copy()
    if agent_name not in retry_count:
        retry_count[agent_name] = 0
    if retryable:
        retry_count[agent_name] += 1

    return update_state_immutable(state, errors=errors, retry_count=retry_count)


def get_retry_count(state: AgentState, agent_name: str) -> int:
    """Get the number of retries for a specific agent.

    Args:
        state: Current state
        agent_name: Name of the agent

    Returns:
        Number of retries attempted
    """
    return state.get("retry_count", {}).get(agent_name, 0)


def should_retry(state: AgentState, agent_name: str) -> bool:
    """Check if an agent should be retried.

    Args:
        state: Current state
        agent_name: Name of the agent

    Returns:
        True if the agent should be retried
    """
    retry_count = get_retry_count(state, agent_name)
    max_retries = state.get("max_retries", 3)
    return retry_count < max_retries


def get_agent_errors(state: AgentState, agent_name: str) -> List[Dict]:
    """Get all errors for a specific agent.

    Args:
        state: Current state
        agent_name: Name of the agent

    Returns:
        List of errors for the agent
    """
    all_errors = state.get("errors", [])
    return [e for e in all_errors if e.get("agent") == agent_name]


def has_errors(state: AgentState, agent_name: Optional[str] = None) -> bool:
    """Check if there are any errors in the state.

    Args:
        state: Current state
        agent_name: Optional agent name to filter by

    Returns:
        True if there are errors
    """
    if agent_name:
        return len(get_agent_errors(state, agent_name)) > 0
    return len(state.get("errors", [])) > 0


def get_execution_summary(state: AgentState) -> Dict[str, Any]:
    """Get a summary of the workflow execution.

    Args:
        state: Current state

    Returns:
        Dictionary containing execution summary
    """
    metadata = state.get("execution_metadata", {})
    outputs = state.get("agent_outputs", [])
    errors = state.get("errors", [])

    completed_agents = set()
    failed_agents = set()

    for output in outputs:
        completed_agents.add(output.get("agent"))

    for error in errors:
        failed_agents.add(error.get("agent"))

    return {
        "workflow_id": metadata.get("workflow_id"),
        "started_at": metadata.get("started_at"),
        "total_agents": len(state.get("agent_status", {})),
        "completed_agents": list(completed_agents),
        "failed_agents": list(failed_agents),
        "total_errors": len(errors),
        "current_step": state.get("current_step", 0),
    }
