"""Tests for the report agent's optional LLM narrative overlay."""

import asyncio
from types import SimpleNamespace

import pytest

from app.agents import ReportGenerationAgent
from app.config import settings

pytestmark = pytest.mark.asyncio


class _StubLLM:
    def __init__(self, content="LLM narrative", delay=0.0):
        self._content = content
        self._delay = delay

    async def ainvoke(self, messages, **kwargs):
        if self._delay:
            await asyncio.sleep(self._delay)
        return SimpleNamespace(content=self._content)


def _state():
    return {
        "query": "Analyze AAPL",
        "symbols": ["AAPL"],
        "market_data": {},
        "technical_analysis": {},
        "fundamental_analysis": {},
        "sentiment_analysis": {},
        "risk_assessment": {},
        "decision": {"decisions": {}},
        "research_synthesis": {},
    }


def _agent(llm=None):
    return ReportGenerationAgent(name="report_generation", llm=llm)


class TestReportLlmOverlay:
    async def test_disabled_by_default_keeps_llm_report_none(self):
        """Flag off: deterministic report ships, LLM never invoked."""
        report = await _agent(llm=_StubLLM()).process(_state())
        assert report["llm_report"] is None
        assert report["sections"]
        assert report["executive_summary"]

    async def test_enabled_populates_llm_report(self, monkeypatch):
        monkeypatch.setattr(settings, "report_llm_enabled", True)
        report = await _agent(llm=_StubLLM(content="Narrative overlay")).process(_state())
        assert report["llm_report"] == "Narrative overlay"

    async def test_timeout_degrades_to_none(self, monkeypatch):
        monkeypatch.setattr(settings, "report_llm_enabled", True)
        monkeypatch.setattr(settings, "report_llm_timeout", 0.05)
        report = await _agent(llm=_StubLLM(delay=0.5)).process(_state())
        assert report["llm_report"] is None
        assert report["sections"]  # deterministic report still ships

    async def test_llm_failure_degrades_to_none(self, monkeypatch):
        class _BrokenLLM:
            async def ainvoke(self, messages, **kwargs):
                raise RuntimeError("provider down")

        monkeypatch.setattr(settings, "report_llm_enabled", True)
        report = await _agent(llm=_BrokenLLM()).process(_state())
        assert report["llm_report"] is None

    async def test_no_llm_configured_stays_none(self, monkeypatch):
        monkeypatch.setattr(settings, "report_llm_enabled", True)
        report = await _agent(llm=None).process(_state())
        assert report["llm_report"] is None


class TestInvokeLlmContentHandling:
    async def test_list_content_blocks_are_joined(self):
        agent = _agent(
            llm=_StubLLM(
                content=[{"type": "text", "text": "alpha"}, {"type": "text", "text": "beta"}]
            )
        )
        assert await agent.invoke_llm("hi") == "alphabeta"

    async def test_string_content_passthrough(self):
        agent = _agent(llm=_StubLLM(content="plain"))
        assert await agent.invoke_llm("hi") == "plain"
