import pytest
from langchain_core.tools import tool

from app.tools.registry import get_all_tools, get_tool, register_tool, clear_registry


@pytest.fixture
def sample_tool():
    @tool
    def mock_tool(query: str) -> str:
        """A mock tool for testing."""
        return f"Result for {query}"
    return mock_tool


@pytest.fixture(autouse=True)
def clean_registry():
    clear_registry()
    yield
    clear_registry()


def test_register_and_get_tool(sample_tool):
    register_tool(sample_tool)

    retrieved = get_tool("mock_tool")
    assert retrieved is sample_tool


def test_get_all_tools(sample_tool):
    register_tool(sample_tool)
    tools = get_all_tools()

    assert len(tools) == 1
    assert tools[0] == sample_tool


def test_get_tool_not_found():
    result = get_tool("nonexistent")
    assert result is None
