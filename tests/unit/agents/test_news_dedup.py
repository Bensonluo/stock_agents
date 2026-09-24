"""News deduplication across symbol fetches.

yfinance returns the same article under every related ticker; a multi-symbol
run must collect one copy, not one per symbol, or sentiment's keyword mean
double-counts and the LLM's 5-headline window fills with repeats.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.agents.data_agent import DataCollectionAgent, _dedup_news

pytestmark = pytest.mark.asyncio


def _article(
    title: str, *, link: str | None = None, related: list[str] | None = None, **extra: Any
) -> dict[str, Any]:
    return {"title": title, "link": link, "related_symbols": related or [], **extra}


class TestDedupNews:
    async def test_same_link_merges_and_unions_related_symbols(self):
        articles = [
            _article("Big merger", link="https://x/1", related=["AAPL"], original_symbol="AAPL"),
            _article("Big merger", link="https://x/1", related=["MSFT"], original_symbol="MSFT"),
        ]
        merged = _dedup_news(articles)

        assert len(merged) == 1
        assert merged[0]["related_symbols"] == ["AAPL", "MSFT"]
        assert merged[0]["original_symbol"] == "AAPL"  # first copy wins

    async def test_title_is_the_key_when_link_missing(self):
        merged = _dedup_news(
            [
                _article("Earnings beat", related=["AAPL"]),
                _article("Earnings beat", related=["MSFT"]),
            ]
        )
        assert len(merged) == 1
        assert merged[0]["related_symbols"] == ["AAPL", "MSFT"]

    async def test_distinct_articles_kept_in_order(self):
        merged = _dedup_news(
            [
                _article("A", link="https://x/a"),
                _article("B", link="https://x/b"),
                _article("A", link="https://x/a", related=["MSFT"]),
            ]
        )
        assert [a["title"] for a in merged] == ["A", "B"]
        assert merged[0]["related_symbols"] == ["MSFT"]  # later copy's tag absorbed

    async def test_article_with_no_link_and_no_title_dropped(self):
        assert _dedup_news([{"summary": "orphan"}]) == []

    async def test_input_articles_not_mutated(self):
        first = _article("A", link="https://x/a", related=["AAPL"])
        _dedup_news([first, _article("A", link="https://x/a", related=["MSFT"])])
        assert first["related_symbols"] == ["AAPL"]


class TestExecuteDedup:
    async def test_execute_merges_cross_symbol_duplicates(self):
        agent = DataCollectionAgent("data_collection")
        agent.llm = None
        per_symbol = {
            "AAPL": {
                "market_data": {"AAPL": {}},
                "financial_data": {"AAPL": {}},
                "news_data": [_article("Fed cuts rates", link="https://x/fed", related=["AAPL"])],
            },
            "MSFT": {
                "market_data": {"MSFT": {}},
                "financial_data": {"MSFT": {}},
                "news_data": [_article("Fed cuts rates", link="https://x/fed", related=["MSFT"])],
            },
        }
        agent._collect_symbol_data = AsyncMock(side_effect=lambda s: per_symbol[s])

        result = await agent.execute({"symbols": ["AAPL", "MSFT"]})

        assert len(result["news_data"]) == 1
        assert result["news_data"][0]["related_symbols"] == ["AAPL", "MSFT"]
        # Both symbols keep their market/financial rows; only news collapses
        assert set(result["market_data"]) == {"AAPL", "MSFT"}
