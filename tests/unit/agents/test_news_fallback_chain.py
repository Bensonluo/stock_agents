"""Multi-symbol Yahoo-dead news fallback chain → sentiment attribution.

Review 2026-09-26, P2#7: Finnhub fallback articles carried no
``original_symbol``/``related_symbols``, while ``SentimentAnalysisAgent``
matches per-symbol news off exactly those fields. With Yahoo dead (the
documented Tencent Cloud state) a two-symbol run analyzed one arbitrary
article for the first symbol and starved the second to ``no_data`` — the
provider adapter now stamps the queried symbol onto every article.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

import app.tools.data.fetcher as fetcher_mod
from app.agents.data_agent import DataCollectionAgent, _dedup_news
from app.agents.sentiment_agent import SentimentAnalysisAgent
from app.config import get_settings

pytestmark = pytest.mark.asyncio


def _finnhub_items(symbol: str, n: int = 3) -> list[dict[str, Any]]:
    """/company-news shaped items; headlines carry positive keywords so the
    deterministic scorer registers each article (score != 0)."""
    now_ts = int(time.time())
    return [
        {
            "headline": f"{symbol} profit rises on strong growth {i}",
            "url": f"https://news.example/{symbol}-{i}",
            "datetime": now_ts - i * 3600,
            "source": "Reuters",
        }
        for i in range(n)
    ]


async def test_multi_symbol_fallback_news_reaches_each_symbols_sentiment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Yahoo dead → Finnhub fallback → execute-level aggregate → sentiment:
    each symbol must analyze its own three articles, not the first symbol's
    arbitrary leftovers."""
    settings = get_settings()
    monkeypatch.setattr(settings, "finnhub_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_sentiment_enabled", False)

    def _dead_yahoo_news(yahoo_symbol: str, symbol: str) -> list[dict[str, Any]]:
        raise RuntimeError("Too Many Requests")

    monkeypatch.setattr("app.agents.data_agent._sync_fetch_news", _dead_yahoo_news)

    by_symbol = {"AAPL": _finnhub_items("AAPL"), "MSFT": _finnhub_items("MSFT")}
    monkeypatch.setattr(
        fetcher_mod, "_finnhub_get", lambda path, params: by_symbol[params["symbol"]]
    )

    agent = DataCollectionAgent("data_collection")
    aapl_articles = await agent._fetch_news("AAPL")
    msft_articles = await agent._fetch_news("MSFT")

    # Provider adapter attributes every article to its queried symbol.
    assert len(aapl_articles) == 3
    assert all(a["original_symbol"] == "AAPL" for a in aapl_articles)
    assert len(msft_articles) == 3
    assert all(a["original_symbol"] == "MSFT" for a in msft_articles)

    # Aggregate the way DataCollectionAgent.execute does, then score.
    news_data = _dedup_news(aapl_articles + msft_articles)
    result = await SentimentAnalysisAgent(name="sentiment").process(
        {"symbols": ["AAPL", "MSFT"], "news_data": news_data}
    )

    aapl_block = result["sentiment_by_symbol"]["AAPL"]
    msft_block = result["sentiment_by_symbol"]["MSFT"]
    assert aapl_block["article_count"] == 3  # pre-fix: 1 (an arbitrary article)
    assert msft_block["article_count"] == 3  # pre-fix: 0 → no_data
