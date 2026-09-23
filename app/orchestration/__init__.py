"""Orchestration module for multi-agent workflow management."""

from app.orchestration.checkpoint import (
    InMemoryCheckpointManager,
    PostgresCheckpointManager,
    SqliteCheckpointManager,
)
from app.orchestration.state import (
    add_agent_output,
    add_error,
    create_initial_state,
    get_agent_errors,
    get_agent_status,
    get_execution_summary,
    get_retry_count,
    has_errors,
    set_agent_status,
    should_retry,
    update_state_immutable,
)


def __getattr__(name: str):
    """Lazily import the orchestrator (PEP 562).

    Importing it eagerly created a cycle: app.agents.base ->
    app.orchestration.state -> app.orchestration.__init__ ->
    orchestrator -> app.agents, which crashed any `import app.agents`
    that ran first. The orchestrator is only needed at wiring time.
    """
    if name == "MultiAgentOrchestrator":
        from app.orchestration.orchestrator import MultiAgentOrchestrator

        return MultiAgentOrchestrator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # State
    "AgentState",
    "create_initial_state",
    "update_state_immutable",
    "get_agent_status",
    "set_agent_status",
    "add_agent_output",
    "add_error",
    "get_retry_count",
    "should_retry",
    "get_agent_errors",
    "has_errors",
    "get_execution_summary",
    # Checkpoint
    "PostgresCheckpointManager",
    "InMemoryCheckpointManager",
    "SqliteCheckpointManager",
    # Orchestrator
    "MultiAgentOrchestrator",
]
