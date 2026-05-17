"""Workflow graph building utilities."""

from typing import Optional

from langchain_core.language_models import BaseChatModel
from langgraph.graph import StateGraph

from app.orchestration.orchestrator import MultiAgentOrchestrator
from app.orchestration.state import AgentState


def build_workflow_graph(
    llm: Optional[BaseChatModel] = None,
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
        "version": "1.0.0",
        "agents": [
            "data_collection",
            "technical_analysis",
            "sentiment_analysis",
            "fundamental_analysis",
            "risk_assessment",
            "decision_making",
            "report_generation",
        ],
        "workflow": [
            ("data_collection", "technical_analysis"),
            ("technical_analysis", "sentiment_analysis"),
            ("sentiment_analysis", "fundamental_analysis"),
            ("fundamental_analysis", "risk_assessment"),
            ("risk_assessment", "decision_making"),
            ("decision_making", "report_generation"),
        ],
        "error_handling": {
            "max_retries": 3,
            "circuit_breaker_enabled": True,
            "timeout_per_agent": 300,
        },
    }
