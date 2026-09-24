"""ReAct news parity: canonical article keys + East Money feed + dedup.

The ReAct tools' news used to be thinner than the pipeline's in three
ways: the fetcher's yfinance provider dropped link/published/related_symbols
(no recency decay, no dedup key), Finnhub shipped the same data under
non-canonical keys (url/datetime — unread by parse_published), and A-shares
had no native CN feed at all. These tests pin the mappers, the shared
dedup helper, and the _fetch_and_split wiring that closes the gap.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from app.tools.analysis import auto_tools
from app.tools.data import fetcher


class TestYfinanceNewsArticles:
    def test_content_shape_maps_to_canonical_keys(self) -> None:
        items = [
            {
                "content": {
                    "title": "Profit surges",
                    "summary": "Full-year results",
                    "canonicalUrl": {"url": "https://a/1"},
                    "provider": {"displayName": "Reuters"},
                    "pubDate": "2026-09-24T10:00:00Z",
                },
                "relatedTickers": ["AAPL"],
            }
        ]

        articles = fetcher.yfinance_news_articles(items, "AAPL")

        assert len(articles) == 1
        first = articles[0]
        assert first["title"] == "Profit surges"
        assert first["link"] == "https://a/1"
        assert first["published"] == "2026-09-24T10:00:00Z"
        assert first["source"] == "Reuters"
        assert first["summary"] == "Full-year results"
        assert first["related_symbols"] == ["AAPL"]
        assert first["original_symbol"] == "AAPL"

    def test_legacy_shape_still_maps(self) -> None:
        items = [
            {
                "title": "Legacy headline",
                "summary": "Legacy body",
                "link": "https://a/2",
                "publisher": "Bloomberg",
                "providerPublishTime": 1789459200,
            }
        ]

        articles = fetcher.yfinance_news_articles(items, "MSFT")

        assert articles[0]["link"] == "https://a/2"
        assert articles[0]["published"] == 1789459200
        assert articles[0]["source"] == "Bloomberg"
        assert "MSFT" in articles[0]["related_symbols"]

    def test_symbol_always_in_related_symbols(self) -> None:
        # A CN query symbol must survive the filter analyze_sentiment applies.
        articles = fetcher.yfinance_news_articles(
            [{"content": {"title": "Wire story"}, "relatedTickers": ["600000.SS"]}], "600000"
        )
        assert set(articles[0]["related_symbols"]) == {"600000.SS", "600000"}

    def test_titleless_item_dropped(self) -> None:
        assert fetcher.yfinance_news_articles([{"content": {}}], "AAPL") == []


class TestFinnhubNewsArticles:
    def test_raw_keys_map_to_canonical(self) -> None:
        articles = fetcher.finnhub_news_articles(
            [
                {
                    "headline": "Earnings beat",
                    "summary": "Raised guidance",
                    "source": "Finnhub",
                    "datetime": 1789459200,
                    "url": "https://b/1",
                }
            ]
        )

        first = articles[0]
        assert first["title"] == "Earnings beat"
        assert first["link"] == "https://b/1"
        assert first["published"] == 1789459200
        assert first["source"] == "Finnhub"

    def test_epoch_published_feeds_recency_decay(self) -> None:
        # The whole point of the key rename: parse_published reads epoch ints,
        # so score_news can weigh the article by its true age.
        from app.analysis.sentiment import parse_published, recency_weight

        articles = fetcher.finnhub_news_articles([{"headline": "x", "datetime": 1789459200}])
        published = parse_published(articles[0]["published"])
        assert published == datetime.fromtimestamp(1789459200, tz=UTC).date()
        assert recency_weight(published) < 1.0  # 2026-09 → decayed today

    def test_headlineless_item_dropped(self) -> None:
        assert fetcher.finnhub_news_articles([{"datetime": 1, "url": "u"}]) == []


class TestDedupNewsSharedHelper:
    def test_same_link_folds_with_related_union(self) -> None:
        first = {"title": "A", "link": "https://same", "related_symbols": ["600000"]}
        dup = {"title": "A (CN copy)", "link": "https://same", "related_symbols": ["600000.SS"]}

        merged = fetcher.dedup_news([first, dup])

        assert len(merged) == 1
        assert merged[0]["title"] == "A"  # first copy wins
        assert set(merged[0]["related_symbols"]) == {"600000", "600000.SS"}

    def test_data_agent_reexports_the_shared_helper(self) -> None:
        # The pipeline's execute() and two test files import _dedup_news from
        # data_agent; the re-export must stay the same object, not a copy.
        from app.agents import data_agent

        assert data_agent._dedup_news is fetcher.dedup_news


def _yf_article(title: str, link: str) -> dict[str, Any]:
    return {
        "title": title,
        "link": link,
        "published": "2026-09-24T10:00:00Z",
        "source": "Reuters",
        "summary": None,
        "related_symbols": ["600000"],
        "original_symbol": "600000",
    }


def _cn_article(title: str, link: str) -> dict[str, Any]:
    return {
        "title": title,
        "link": link,
        "published": "2026-09-24 21:35:00",
        "source": "证券时报",
        "summary": None,
        "related_symbols": ["600000"],
        "original_symbol": "600000",
    }


class TestAugmentNewsSeam:
    @pytest.mark.asyncio
    async def test_cn_symbol_gets_both_feeds_deduped(self, monkeypatch) -> None:
        cn_calls: list[str] = []
        cn_feed = [
            _cn_article("同一篇的中文版", "https://en"),  # syndicated copy of the EN story
            _cn_article("中文", "https://cn"),
        ]
        monkeypatch.setattr(
            auto_tools,
            "fetch_cn_news",
            lambda s: (cn_calls.append(s), cn_feed)[1],
        )

        merged = await auto_tools._augment_news("600000", [_yf_article("English", "https://en")])

        assert cn_calls == ["600000"]
        assert [a["title"] for a in merged] == ["English", "中文"]  # syndicated copy folded
        assert set(merged[0]["related_symbols"]) == {"600000"}  # union kept intact

    @pytest.mark.asyncio
    async def test_cn_feed_failure_degrades_to_base(self, monkeypatch) -> None:
        def failing(s: str):
            raise RuntimeError("eastmoney down")

        monkeypatch.setattr(auto_tools, "fetch_cn_news", failing)

        base = [_yf_article("English", "https://en")]
        assert await auto_tools._augment_news("600000", base) == base

    @pytest.mark.asyncio
    async def test_us_symbol_never_touches_cn_feed(self, monkeypatch) -> None:
        def forbidden(s: str):
            raise AssertionError("CN feed must not be called for US symbols")

        monkeypatch.setattr(auto_tools, "fetch_cn_news", forbidden)

        base = [_yf_article("English", "https://en")]
        assert await auto_tools._augment_news("AAPL", base) == base


def _snapshot(s: str, news: list[dict[str, Any]]) -> dict[str, Any]:
    """Provider-chain result in the FLAT shape fetch_stock_data returns —
    market_data is the market block itself, not keyed by symbol (keying by
    symbol here makes _fetch_and_split miss historical_data and leak a real
    fetch_historical call; see the iteration-60 lesson on hermetic tests)."""
    return {
        "market_data": {
            "symbol": s,
            "current_price": 100.0,
            "historical_data": {"dates": ["2026-09-22", "2026-09-23"], "close": [99.0, 100.0]},
        },
        "financial_data": {},
        "news_data": news,
    }


class TestFetchAndSplitWiring:
    @staticmethod
    def _patch_network(monkeypatch) -> None:
        # _attach_benchmark touches the benchmark cache seam; keep it offline.
        async def no_bench(t: str):
            return None

        async def no_cn_bench(s: str):
            return None

        monkeypatch.setattr(auto_tools, "fetch_benchmark_history", no_bench)
        monkeypatch.setattr(auto_tools, "fetch_cn_sector_benchmark", no_cn_bench)

    @pytest.mark.asyncio
    async def test_snapshot_path_augments_cn_news(self, monkeypatch) -> None:
        self._patch_network(monkeypatch)
        auto_tools._reset_fetch_failures("600519")

        async def fake_snapshot(s: str) -> dict[str, Any]:
            return _snapshot(s, [_yf_article("English", "https://en")])

        monkeypatch.setattr(auto_tools, "fetch_stock_data", fake_snapshot)
        monkeypatch.setattr(
            auto_tools, "fetch_cn_news", lambda s: [_cn_article("贵州茅台涨停", "https://cn")]
        )

        data = await auto_tools._fetch_and_split("600519")
        titles = [a["title"] for a in data["news_data"]]
        assert titles == ["English", "贵州茅台涨停"]

    @pytest.mark.asyncio
    async def test_history_fallback_path_still_gets_cn_news(self, monkeypatch) -> None:
        # Snapshot chain fully down — the CN feed must still power sentiment
        # (independent degradation, same property the pipeline seam has).
        self._patch_network(monkeypatch)
        auto_tools._reset_fetch_failures("600036")

        async def no_snapshot(s: str):
            return None

        async def fake_hist(s: str, period: str = "3y") -> dict[str, Any]:
            return {"dates": ["2026-09-22", "2026-09-23"], "close": [38.0, 39.0], "volume": [1, 2]}

        monkeypatch.setattr(auto_tools, "fetch_stock_data", no_snapshot)
        monkeypatch.setattr(auto_tools, "fetch_historical", fake_hist)
        monkeypatch.setattr(
            auto_tools, "fetch_cn_news", lambda s: [_cn_article("招行新闻", "https://cn")]
        )

        data = await auto_tools._fetch_and_split("600036")
        assert [a["title"] for a in data["news_data"]] == ["招行新闻"]

    @pytest.mark.asyncio
    async def test_us_symbol_snapshot_path_unchanged(self, monkeypatch) -> None:
        self._patch_network(monkeypatch)
        auto_tools._reset_fetch_failures("MSFT")

        base_news = [
            {
                "title": "Azure growth",
                "link": "https://msft",
                "published": "2026-09-24T10:00:00Z",
                "source": "Reuters",
                "summary": None,
                "related_symbols": ["MSFT"],
                "original_symbol": "MSFT",
            }
        ]

        async def fake_snapshot(s: str) -> dict[str, Any]:
            return _snapshot(s, base_news)

        monkeypatch.setattr(auto_tools, "fetch_stock_data", fake_snapshot)

        def forbidden(s: str):
            raise AssertionError("CN feed must not be called for US symbols")

        monkeypatch.setattr(auto_tools, "fetch_cn_news", forbidden)

        data = await auto_tools._fetch_and_split("MSFT")
        assert data["news_data"] == base_news

    @pytest.mark.asyncio
    async def test_recency_reaches_the_sentiment_tool(self, monkeypatch) -> None:
        # End-to-end pin: a stale yfinance-provider article now carries its
        # publish date into score_news, so it weighs less than a fresh one.
        self._patch_network(monkeypatch)
        auto_tools._reset_fetch_failures("NVDA")

        news = fetcher.yfinance_news_articles(
            [
                {
                    "content": {
                        "title": "Fresh profit surge",
                        "pubDate": date.today().isoformat() + "T10:00:00Z",
                    }
                },
                {
                    "content": {
                        "title": "Stale profit surge",
                        "pubDate": "2020-01-01T10:00:00Z",
                    }
                },
            ],
            "NVDA",
        )

        async def fake_snapshot(s: str) -> dict[str, Any]:
            return _snapshot(s, news)

        monkeypatch.setattr(auto_tools, "fetch_stock_data", fake_snapshot)

        data = await auto_tools._fetch_and_split("NVDA")
        result = auto_tools.score_news(data["news_data"])
        # Two equal keyword scores (+2 each), but the 2020 copy is decayed to
        # ~0: the mean lands at 20, half the fresh-only score of 40.
        assert result["article_count"] == 2
        assert result["score"] == 20
