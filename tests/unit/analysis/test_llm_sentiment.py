"""LLM semantic sentiment layer: per-article scores in keyword-compatible
units, injected at the canonical seam, with the keyword scorer as floor.

Also pins the ReAct ``analyze_sentiment`` tool to the canonical module
output (the inline keyword copy that had drifted from it was removed).
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from app.agents import sentiment_agent as sentiment_agent_module
from app.agents.sentiment_agent import SentimentAnalysisAgent
from app.analysis.sentiment import (
    llm_article_scores,
    score_news,
    score_news_with_llm,
)
from app.tools.analysis import auto_tools

pytestmark = pytest.mark.asyncio


class _FakeLlm:
    """Prompt-path stub: no ``with_structured_output``, plain ``ainvoke``.

    ainvoke_json falls back to the plain-ainvoke + extract_json path when
    the native structured-output method is unavailable.
    """

    def __init__(self, content: str):
        self.content = content
        self.calls = 0

    async def ainvoke(self, messages, **kwargs):  # noqa: ARG002
        self.calls += 1
        return SimpleNamespace(content=self.content)


class _Flag:
    """Minimal settings stand-in for the agent flag tests."""

    def __init__(self, enabled: bool):
        self.llm_sentiment_enabled = enabled


def _news(*titles: str) -> list[dict[str, Any]]:
    return [{"title": t, "summary": ""} for t in titles]


# ----------------------------------------------------------------------
# llm_article_scores: contract enforcement on the wire output
# ----------------------------------------------------------------------


async def test_llm_scores_roundtrip() -> None:
    news = _news("a", "b", "c")
    llm = _FakeLlm('{"scores": [3, -1, 0]}')
    assert await llm_article_scores(news, llm) == [3, -1, 0]
    assert llm.calls == 1


async def test_wrong_length_degrades_to_none() -> None:
    news = _news("a", "b", "c")
    llm = _FakeLlm('{"scores": [1]}')
    assert await llm_article_scores(news, llm) is None


async def test_out_of_range_degrades_to_none() -> None:
    news = _news("a", "b")
    llm = _FakeLlm('{"scores": [6, 0]}')
    assert await llm_article_scores(news, llm) is None


async def test_non_integer_degrades_to_none() -> None:
    news = _news("a", "b")
    llm = _FakeLlm('{"scores": [1.5, 0]}')
    assert await llm_article_scores(news, llm) is None


async def test_garbage_response_degrades_to_none() -> None:
    news = _news("a")
    llm = _FakeLlm("not json at all")
    assert await llm_article_scores(news, llm) is None


async def test_over_volume_skips_the_llm_entirely() -> None:
    news = _news(*[f"headline {i}" for i in range(31)])
    llm = _FakeLlm("{}")
    assert await llm_article_scores(news, llm) is None
    assert llm.calls == 0


# ----------------------------------------------------------------------
# score_news with injected scores: same math, semantic provenance
# ----------------------------------------------------------------------


async def test_injected_scores_flow_through_normalization() -> None:
    news = _news("bullish", "bearish")
    block = score_news(news, article_scores=[4, -2])

    assert block["article_count"] == 2  # every article is semantically analyzed
    assert block["score"] == pytest.approx(20.0)  # ((4 - 2) / 2) * 20
    assert block["sentiment"] == "positive"
    assert block["recent_scores"] == [4, -2]
    assert block["scoring"] == "llm_semantic"


async def test_zero_scores_count_as_analyzed() -> None:
    # A semantic 0 is information, not an absence — unlike the keyword path
    # where a 0-score headline is skipped entirely.
    news = _news("meh", "meh")
    block = score_news(news, article_scores=[0, 0])

    assert block["article_count"] == 2
    assert block["score"] == 0
    assert block["sentiment"] == "neutral"


async def test_keyword_path_is_unchanged_no_provenance_key() -> None:
    news = [{"title": "record profit surge", "summary": "growth"}]
    block = score_news(news)

    assert "scoring" not in block
    assert block["article_count"] == 1
    assert block["score"] == pytest.approx(80.0)  # 4 keyword hits * 20
    assert block["sentiment"] == "very_positive"


async def test_injected_scores_still_decay_with_recency() -> None:
    news = [
        {"title": "a", "summary": "", "published": "2026-01-01"},
        {"title": "b", "summary": "", "published": "2026-01-01"},
    ]
    fresh = score_news(news, now=date(2026, 1, 1), article_scores=[4, 4])
    stale = score_news(news, now=date(2026, 1, 29), article_scores=[4, 4])

    assert fresh["score"] == pytest.approx(80.0)
    assert stale["score"] == pytest.approx(20.0)  # 14-day half-life, 28 days old


# ----------------------------------------------------------------------
# score_news_with_llm: the switch with keyword as floor
# ----------------------------------------------------------------------


async def test_score_news_with_llm_uses_semantic_scores() -> None:
    news = _news("a", "b")
    llm = _FakeLlm('{"scores": [5, 5]}')
    block = await score_news_with_llm(news, llm)

    assert block["scoring"] == "llm_semantic"
    assert block["score"] == pytest.approx(100.0)
    assert block["sentiment"] == "very_positive"


async def test_score_news_with_llm_falls_back_bit_for_bit() -> None:
    news = _news("record profit")
    llm = _FakeLlm("garbage")

    block = await score_news_with_llm(news, llm)

    assert block == score_news(news)  # exact keyword fallback parity


# ----------------------------------------------------------------------
# Agent wiring: flag on -> semantic, flag off -> keyword floor
# ----------------------------------------------------------------------


async def test_agent_flag_off_keeps_keyword_scoring(monkeypatch) -> None:
    monkeypatch.setattr(sentiment_agent_module, "get_settings", lambda: _Flag(False))
    agent = SentimentAnalysisAgent(name="sentiment", llm=_FakeLlm('{"scores": [5, 5]}'))

    block = await agent._analyze_news_sentiment(_news("nothing keywordy here"))

    assert "scoring" not in block  # keyword floor


async def test_agent_flag_on_uses_semantic_scoring(monkeypatch) -> None:
    monkeypatch.setattr(sentiment_agent_module, "get_settings", lambda: _Flag(True))
    agent = SentimentAnalysisAgent(name="sentiment", llm=_FakeLlm('{"scores": [5]}'))

    block = await agent._analyze_news_sentiment(_news("nothing keywordy here"))

    assert block["scoring"] == "llm_semantic"
    assert block["score"] == pytest.approx(100.0)


# ----------------------------------------------------------------------
# ReAct tool convergence: canonical output, no inline copy
# ----------------------------------------------------------------------


async def test_react_sentiment_tool_matches_canonical(monkeypatch) -> None:
    news = [
        {"title": "record profit", "summary": "growth", "related_symbols": ["AAPL"]},
        {"title": "lawsuit risk", "summary": "", "related_symbols": ["AAPL"]},
    ]

    async def fake_split(_symbol: str):
        return {"market_data": {}, "financial_data": {}, "news_data": news}

    monkeypatch.setattr(auto_tools, "_fetch_and_split", fake_split)

    result = await auto_tools.analyze_sentiment.ainvoke({"symbol": "AAPL"})

    assert result["sentiment"] == score_news(news)  # bit-for-bit canonical parity
    assert result["headlines"] == ["record profit", "lawsuit risk"]
