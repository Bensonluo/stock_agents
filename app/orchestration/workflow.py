"""Workflow graph building utilities."""

from langchain_core.language_models import BaseChatModel
from langgraph.graph import StateGraph

from app.orchestration.orchestrator import MultiAgentOrchestrator


def build_workflow_graph(
    llm: BaseChatModel | None = None,
    checkpoint_manager=None,
) -> StateGraph:
    """Build the LangGraph workflow for stock analysis.

    This is a convenience function that creates an orchestrator
    and returns the built graph.

    Args:
        llm: Optional language model
        checkpoint_manager: Optional checkpoint manager

    Returns:
        Compiled StateGraph
    """
    orchestrator = MultiAgentOrchestrator(
        llm=llm,
        checkpoint_manager=checkpoint_manager,
    )
    orchestrator._build_graph()

    return orchestrator.graph


def get_workflow_summary() -> dict:
    """Get a summary of the workflow structure.

    Returns:
        Dictionary containing workflow information
    """
    return {
        "name": "Stock Analysis Multi-Agent Workflow",
        "version": "2.0.0",
        "agents": [
            "data_collection",
            "technical_analysis",
            "sentiment_analysis",
            "fundamental_analysis",
            "risk_assessment",
            "research_synthesis",
            "decision_making",
            "report_generation",
        ],
        "workflow": [
            ("data_collection", "technical_analysis"),
            # Fan-out: the three analysis agents run in the same superstep.
            ("data_collection", "sentiment_analysis"),
            ("data_collection", "fundamental_analysis"),
            ("technical_analysis", "risk_assessment"),
            ("sentiment_analysis", "risk_assessment"),
            ("fundamental_analysis", "risk_assessment"),
            ("risk_assessment", "research_synthesis"),
            ("research_synthesis", "decision_making"),
            ("decision_making", "report_generation"),
        ],
        "parallel_execution": {
            "enabled_by_default": True,
            "stages": [["technical_analysis", "sentiment_analysis", "fundamental_analysis"]],
            "toggle": "parallel_execution in the initial state / analyze request",
        },
        "error_handling": {
            "max_retries": 3,
            "circuit_breaker_enabled": True,
            "timeout_per_agent": 300,
            "analysis_failure_policy": "degrade_gracefully",
            "critical_failure_policy": "error_handler",
        },
    }
