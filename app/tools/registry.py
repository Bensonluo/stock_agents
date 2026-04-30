"""Tool registry for the ReAct agent.

Tools are registered centrally so the agent can discover and invoke them.
"""

from typing import Optional

from langchain_core.tools import BaseTool

# Global tool registry
_TOOLS: dict[str, BaseTool] = {}


def register_tool(tool: BaseTool) -> None:
    """Register a tool in the global registry.

    Args:
        tool: A LangChain tool instance
    """
    _TOOLS[tool.name] = tool


def get_tool(name: str) -> Optional[BaseTool]:
    """Get a tool by name.

    Args:
        name: Tool name

    Returns:
        The tool or None if not found
    """
    return _TOOLS.get(name)


def get_all_tools() -> list[BaseTool]:
    """Get all registered tools.

    Returns:
        List of all registered tools
    """
    return list(_TOOLS.values())


def clear_registry() -> None:
    """Clear all registered tools. Useful for testing."""
    _TOOLS.clear()
