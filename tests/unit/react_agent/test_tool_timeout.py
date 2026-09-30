"""ReAct tool-invocation timeout (iteration 175).

`tool_execute_node` awaits `tool.ainvoke(...)` with no bound. HTTP fetchers
carry their own 15-20s timeouts and the LLM client 90s, but a tool whose
internal call hangs never raises — the loop stalls forever and, since the
iteration-170 capacity gate, holds an analysis slot indefinitely. The
pipeline's StatelessAgent nodes got the same treatment in iteration 173.
"""

import asyncio
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from app.config import Settings, settings
from app.react_agent.react_agent import tool_execute_node

pytestmark = pytest.mark.asyncio


class _FakeTool:
    """Tool stub with configurable latency. `hang=True` simulates an
    upstream call that never returns (the unbounded failure mode)."""

    def __init__(self, hang: bool = False, delay: float = 0.0):
        self._hang = hang
        self._delay = delay

    async def ainvoke(self, args: dict) -> dict:
        if self._hang:
            await asyncio.sleep(30)  # "forever" for test purposes
            return {}
        await asyncio.sleep(self._delay)
        return {"symbol": "AAPL", "ok": True}


def _make_state() -> dict:
    return {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "fake_tool", "args": {}, "id": "call_1"}],
            )
        ],
        "tools_used": [],
        "tool_call_history": [],
        "errors": [],
        "tool_results": {},
    }


async def _run_node_with_antihang_guard(state: dict) -> dict:
    """Outer 15s bound so the RED phase fails fast instead of hanging the
    suite (iteration-173 pattern: an unimplemented guard would wait on the
    hung stub for the full 30s sleep — or worse, forever in production)."""
    return await asyncio.wait_for(tool_execute_node(state), 15)


class TestHungToolIsBounded:
    async def test_timeout_kills_hung_tool_and_degrades(self, monkeypatch):
        monkeypatch.setattr(settings, "react_tool_timeout", 0.05)
        monkeypatch.setattr(
            "app.react_agent.react_agent.get_tool", lambda name: _FakeTool(hang=True)
        )

        update = await _run_node_with_antihang_guard(_make_state())

        timeouts = [e for e in update["errors"] if e["error_type"] == "ToolTimeout"]
        assert len(timeouts) == 1
        assert "exceeded react_tool_timeout=0.05s" in timeouts[0]["message"]
        # The loop's existing degradation contract: the error goes to the
        # LLM as a ToolMessage so the agent can route around the failure.
        assert "exceeded react_tool_timeout" in update["messages"][0].content


class TestDisableAndDefaults:
    async def test_zero_disables_the_bound(self, monkeypatch):
        monkeypatch.setattr(settings, "react_tool_timeout", 0)
        monkeypatch.setattr(
            "app.react_agent.react_agent.get_tool",
            lambda name: _FakeTool(delay=0.05),
        )

        update = await _run_node_with_antihang_guard(_make_state())

        assert update["errors"] == []
        assert update["tool_results"]["fake_tool"]["AAPL"]["ok"] is True

    async def test_default_budget_harmless_to_fast_tools(self, monkeypatch):
        # No timeout monkeypatch: the shipped default must not clip real
        # tool calls (fetch HTTP ceilings are 15-20s, well under the budget).
        monkeypatch.setattr(
            "app.react_agent.react_agent.get_tool",
            lambda name: _FakeTool(delay=0.01),
        )

        update = await _run_node_with_antihang_guard(_make_state())

        assert update["errors"] == []
        assert update["tool_results"]["fake_tool"]["AAPL"]["ok"] is True


class TestWiring:
    async def test_default_is_120_and_documented(self):
        assert settings.react_tool_timeout == 120.0
        assert Settings.model_fields["react_tool_timeout"].default == 120.0

        env_example = (Path(__file__).parents[3] / ".env.example").read_text()
        assert "REACT_TOOL_TIMEOUT" in env_example
