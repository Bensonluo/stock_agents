"""Concurrency pin for the synthesis agent's two LLM enhancement layers.

``narrate_synthesis`` and ``attach_analyst_panel`` are independent: both
serialize their prompts before awaiting the LLM, then write disjoint keys
(``narrative`` vs ``analysts``/``pm``) into the shared synthesis dict, so the
agent runs them concurrently via ``asyncio.gather``. Worst-case wall time is
``max(narration, panel)`` instead of the sum. The first test deadlocks by
construction under sequential execution — the fake narrator blocks on an
Event that only the fake panel can set.
"""

from __future__ import annotations

import asyncio

import pytest

import app.agents.synthesis_agent as synthesis_agent_mod
from app.agents.synthesis_agent import ResearchSynthesisAgent

pytestmark = pytest.mark.asyncio


def _state() -> dict:
    return {
        "query": "test",
        "symbols": ["AAPL"],
        "market_data": {},
        "technical_analysis": {},
        "fundamental_analysis": {},
        "sentiment_analysis": {},
        "risk_assessment": {},
    }


async def test_enhancement_layers_run_concurrently(monkeypatch: pytest.MonkeyPatch) -> None:
    """Narrator and panel must overlap. The narrator awaits an Event that only
    the panel sets: sequentially this deadlocks past the wait_for budget;
    under gather the panel sets the Event, both layers write, and the final
    synthesis carries narrative AND analysts/pm."""
    panel_ran = asyncio.Event()

    async def _fake_narrator(synthesis, *, llm):
        await panel_ran.wait()  # only resolvable while the panel is running
        synthesis["per_symbol"]["AAPL"]["narrative"] = {"bull_narrative": "b", "pm_comment": "c"}
        return synthesis

    async def _fake_panel(synthesis, *, llm):
        panel_ran.set()
        synthesis["per_symbol"]["AAPL"]["analysts"] = {"technical": {"view": "v", "cites": ["r"]}}
        synthesis["per_symbol"]["AAPL"]["pm"] = {"thesis": "t"}
        return synthesis

    monkeypatch.setattr(synthesis_agent_mod, "narrate_synthesis", _fake_narrator)
    monkeypatch.setattr(synthesis_agent_mod, "attach_analyst_panel", _fake_panel)

    agent = ResearchSynthesisAgent("test-synthesis", llm=object())

    result = await asyncio.wait_for(agent.process(_state()), timeout=5.0)

    entry = result["research_synthesis"]["per_symbol"]["AAPL"]
    assert entry["narrative"] == {"bull_narrative": "b", "pm_comment": "c"}
    assert entry["analysts"] == {"technical": {"view": "v", "cites": ["r"]}}
    assert entry["pm"] == {"thesis": "t"}


async def test_llm_none_skips_both_enhancement_layers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without an LLM the deterministic synthesis flows on untouched — neither
    enhancement layer may even be called."""

    async def _forbidden(*args, **kwargs):
        raise AssertionError("enhancement layers must not run without an LLM")

    monkeypatch.setattr(synthesis_agent_mod, "narrate_synthesis", _forbidden)
    monkeypatch.setattr(synthesis_agent_mod, "attach_analyst_panel", _forbidden)

    agent = ResearchSynthesisAgent("test-synthesis", llm=None)

    result = await asyncio.wait_for(agent.process(_state()), timeout=5.0)

    entry = result["research_synthesis"]["per_symbol"]["AAPL"]
    assert "narrative" not in entry
    assert "analysts" not in entry
    assert "pm" not in entry
    assert result["research_synthesis"]["audit"]["verdict"]
