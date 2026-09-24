"""A-share native news attach + fetcher column mapping.

yfinance serves A-share symbols sparsely and in English; the pipeline's
_fetch_news seam augments 6-digit symbols with the East Money feed
(akshare stock_news_em). These tests pin the column mapping, the
concatenate-and-degrade contract, and that US symbols never touch the
CN feed.
"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

import pandas as pd
import pytest

from app.agents.data_agent import DataCollectionAgent, _dedup_news


def _cn_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "关键词": ["600000", "600000"],
            "新闻标题": ["净利润同比增长20%", "公司遭证监会处罚"],
            "新闻内容": ["内容甲" * 200, "内容乙"],
            "发布时间": ["2026-09-24 21:35:00", "2026-09-23 09:00:00"],
            "文章来源": ["证券时报", "财联社"],
            "新闻链接": [
                "http://finance.eastmoney.com/a/1.html",
                "http://finance.eastmoney.com/a/2.html",
            ],
        }
    )


def _install_fake_akshare(monkeypatch, df: pd.DataFrame | None, calls: list[str]) -> None:
    fake = ModuleType("akshare")

    def stock_news_em(symbol: str) -> pd.DataFrame:
        calls.append(symbol)
        if df is None:
            raise RuntimeError("news feed down")
        return df

    fake.stock_news_em = stock_news_em
    monkeypatch.setitem(sys.modules, "akshare", fake)


class TestFetcherCnNewsMapping:
    def test_maps_east_money_columns_into_article_shape(self, monkeypatch) -> None:
        from app.tools.data import fetcher

        calls: list[str] = []
        _install_fake_akshare(monkeypatch, _cn_df(), calls)

        articles = fetcher.fetch_cn_news("600000")

        assert calls == ["600000"]
        assert articles is not None and len(articles) == 2
        first = articles[0]
        assert first["title"] == "净利润同比增长20%"
        assert first["link"] == "http://finance.eastmoney.com/a/1.html"
        assert first["published"] == "2026-09-24 21:35:00"
        assert first["source"] == "证券时报"
        assert len(first["summary"]) == 300  # truncated from 600 chars
        assert first["related_symbols"] == ["600000"]
        assert first["original_symbol"] == "600000"

    def test_failures_return_none_not_an_empty_list(self, monkeypatch) -> None:
        from app.tools.data import fetcher

        calls: list[str] = []
        _install_fake_akshare(monkeypatch, None, calls)
        assert fetcher.fetch_cn_news("600000") is None

        # Empty frame and missing title column are the same non-event.
        _install_fake_akshare(monkeypatch, pd.DataFrame(), calls)
        assert fetcher.fetch_cn_news("600000") is None

    def test_missing_akshare_returns_none(self, monkeypatch) -> None:
        from app.tools.data import fetcher

        # A None entry in sys.modules makes `import akshare` raise ImportError.
        monkeypatch.setitem(sys.modules, "akshare", None)
        assert fetcher.fetch_cn_news("600000") is None

    def test_rows_without_titles_are_skipped(self, monkeypatch) -> None:
        from app.tools.data import fetcher

        df = _cn_df()
        df.loc[0, "新闻标题"] = ""
        calls: list[str] = []
        _install_fake_akshare(monkeypatch, df, calls)

        articles = fetcher.fetch_cn_news("600000")
        assert articles is not None and len(articles) == 1
        assert articles[0]["title"] == "公司遭证监会处罚"


class TestFetchNewsSeam:
    """DataCollectionAgent._fetch_news concatenates feeds for A-shares."""

    @staticmethod
    def _yf_article(title: str, link: str) -> dict[str, Any]:
        return {
            "title": title,
            "link": link,
            "published": "2026-09-24T10:00:00",
            "source": "Reuters",
            "summary": None,
            "related_symbols": ["600000", "600000.SS"],
            "original_symbol": "600000",
        }

    @pytest.mark.asyncio
    async def test_cn_symbol_gets_both_feeds(self, monkeypatch) -> None:
        import app.agents.data_agent as module

        yf_articles = [self._yf_article("English headline", "http://a")]
        monkeypatch.setattr(module, "_sync_fetch_news", lambda y, s: yf_articles)

        cn_articles = [
            {
                "title": "中文标题",
                "link": "http://b",
                "published": "2026-09-24 21:35:00",
                "source": "证券时报",
                "summary": None,
                "related_symbols": ["600000"],
                "original_symbol": "600000",
            }
        ]
        cn_calls: list[str] = []
        monkeypatch.setattr(module, "fetch_cn_news", lambda s: (cn_calls.append(s), cn_articles)[1])

        articles = await DataCollectionAgent(name="data_collection")._fetch_news("600000")

        assert cn_calls == ["600000"]
        assert [a["title"] for a in articles] == ["English headline", "中文标题"]

    @pytest.mark.asyncio
    async def test_cn_feed_failure_degrades_to_yfinance_only(self, monkeypatch) -> None:
        import app.agents.data_agent as module

        yf_articles = [self._yf_article("English headline", "http://a")]
        monkeypatch.setattr(module, "_sync_fetch_news", lambda y, s: yf_articles)

        cn_calls: list[str] = []

        def failing(s: str) -> list | None:
            cn_calls.append(s)
            raise RuntimeError("eastmoney down")

        monkeypatch.setattr(module, "fetch_cn_news", failing)

        articles = await DataCollectionAgent(name="data_collection")._fetch_news("600000")

        assert cn_calls == ["600000"]  # attempted…
        assert articles == yf_articles  # …but the primary feed survives intact

    @pytest.mark.asyncio
    async def test_cn_none_result_degrades_silently(self, monkeypatch) -> None:
        import app.agents.data_agent as module

        yf_articles = [self._yf_article("English headline", "http://a")]
        monkeypatch.setattr(module, "_sync_fetch_news", lambda y, s: yf_articles)
        monkeypatch.setattr(module, "fetch_cn_news", lambda s: None)

        assert (
            await DataCollectionAgent(name="data_collection")._fetch_news("600000") == yf_articles
        )

    @pytest.mark.asyncio
    async def test_us_symbol_never_touches_the_cn_feed(self, monkeypatch) -> None:
        import app.agents.data_agent as module

        yf_articles = [self._yf_article("AAPL headline", "http://a")]
        monkeypatch.setattr(module, "_sync_fetch_news", lambda y, s: yf_articles)

        def forbidden(s: str):
            raise AssertionError("CN feed must not be called for US symbols")

        monkeypatch.setattr(module, "fetch_cn_news", forbidden)

        assert await DataCollectionAgent(name="data_collection")._fetch_news("AAPL") == yf_articles

    @pytest.mark.asyncio
    async def test_yfinance_failure_still_gets_cn_news(self, monkeypatch) -> None:
        import app.agents.data_agent as module

        def yf_fails(y, s):
            raise RuntimeError("yahoo 429")

        monkeypatch.setattr(module, "_sync_fetch_news", yf_fails)

        cn_articles = [
            {
                "title": "中文标题",
                "link": "http://b",
                "published": "2026-09-24 21:35:00",
                "source": "证券时报",
                "summary": None,
                "related_symbols": ["600000"],
                "original_symbol": "600000",
            }
        ]
        monkeypatch.setattr(module, "fetch_cn_news", lambda s: cn_articles)

        articles = await DataCollectionAgent(name="data_collection")._fetch_news("600000")
        assert [a["title"] for a in articles] == ["中文标题"]


class TestCrossSourceDedup:
    def test_same_link_across_feeds_collapses(self) -> None:
        # East Money occasionally syndicates Reuters/AP wire stories that
        # yfinance also carries — the execute-level dedup must fold them.
        yf_article = {
            "title": "English headline",
            "link": "http://same",
            "related_symbols": ["600000", "600000.SS"],
            "original_symbol": "600000",
        }
        cn_article = {
            "title": "同一篇文章的中文版",
            "link": "http://same",
            "related_symbols": ["600000"],
            "original_symbol": "600000",
        }

        merged = _dedup_news([yf_article, cn_article])

        assert len(merged) == 1
        assert merged[0]["title"] == "English headline"  # first copy wins
        assert set(merged[0]["related_symbols"]) == {"600000", "600000.SS"}
