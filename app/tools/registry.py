"""Tool registry for the ReAct agent."""

from typing import Optional

from langchain_core.tools import BaseTool

_TOOLS: dict[str, BaseTool] = {}


def register_tool(tool: BaseTool) -> None:
    _TOOLS[tool.name] = tool


def get_tool(name: str) -> Optional[BaseTool]:
    return _TOOLS.get(name)


def get_all_tools() -> list[BaseTool]:
    return list(_TOOLS.values())


def clear_registry() -> None:
    _TOOLS.clear()
