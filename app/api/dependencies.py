"""API dependency injection utilities."""

from typing import Optional

from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver

from app.config import settings
from app.orchestration import PostgresCheckpointManager
from app.orchestration.orchestrator import MultiAgentOrchestrator
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Global orchestrator instance
_orchestrator: Optional[MultiAgentOrchestrator] = None


def get_llm():
    """Get the LLM instance.

    Supports:
    - OpenAI (GPT-4, GPT-3.5)
    - Zhipu AI (GLM-4, GLM-4-Plus, GLM-4-Air, etc.)

    Returns:
        ChatOpenAI instance or None
    """
    # Zhipu AI (GLM) - has priority if configured
    if settings.zhipuai_api_key:
        logger.info(f"Using Zhipu AI GLM model: {settings.primary_llm_model}")

        # Zhipu AI uses OpenAI-compatible API
        return ChatOpenAI(
            model=settings.primary_llm_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            timeout=settings.llm_timeout,
            openai_api_key=settings.zhipuai_api_key,
            openai_api_base="https://open.bigmodel.cn/api/paas/v4/",
        )

    # OpenAI fallback
    if settings.openai_api_key:
        logger.info(f"Using OpenAI model: {settings.primary_llm_model}")

        return ChatOpenAI(
            model=settings.primary_llm_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            timeout=settings.llm_timeout,
        )

    logger.warning("No API key configured (set ZHIPUAI_API_KEY or OPENAI_API_KEY), LLM features will be limited")
    return None


def get_checkpoint_manager():
    """Get the checkpoint manager instance.

    Returns:
        CheckpointManager instance
    """
    try:
        # Try PostgreSQL checkpoint manager
        return PostgresCheckpointManager(settings.database_url)
    except Exception as e:
        logger.warning(f"Could not initialize PostgreSQL checkpoint manager: {e}")
        logger.info("Using in-memory checkpoint manager")
        from app.orchestration import InMemoryCheckpointManager
        return InMemoryCheckpointManager()


def get_orchestrator() -> MultiAgentOrchestrator:
    """Get the global orchestrator instance.

    Returns:
        MultiAgentOrchestrator instance
    """
    global _orchestrator

    if _orchestrator is None:
        llm = get_llm()
        checkpoint_manager = get_checkpoint_manager()

        _orchestrator = MultiAgentOrchestrator(
            llm=llm,
            checkpoint_manager=checkpoint_manager,
        )

        logger.info("Orchestrator initialized")

    return _orchestrator


def reset_orchestrator():
    """Reset the global orchestrator instance."""
    global _orchestrator
    _orchestrator = None
    logger.info("Orchestrator reset")
