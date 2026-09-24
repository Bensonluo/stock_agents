"""Bilingual keyword scoring: A-share headlines arrive in Chinese.

The East Money news feed (fetch_cn_news) ships native Chinese headlines;
the deterministic keyword floor must read those as fluently as English —
otherwise A-share sentiment is a permanent neutral mask. Chinese word
boundaries don't exist, so substring matching is the same crude-but-fair
mechanism the English lists use; the LLM scorer stays the semantic upgrade.
"""

from __future__ import annotations

from datetime import date

from app.analysis.sentiment import parse_published, score_news


class TestChineseKeywordScoring:
    def test_positive_chinese_headline_scores_positive(self) -> None:
        # 增长 + 新高 -> +2 per article; (2*20) hits the very_positive band.
        block = score_news(
            [{"title": "净利润同比增长20%，股价创年内新高", "published": "2026-09-24 10:00:00"}],
            now=date(2026, 9, 24),
        )
        assert block["score"] == 40
        assert block["sentiment"] == "very_positive"
        assert block["article_count"] == 1

    def test_negative_chinese_headline_scores_negative(self) -> None:
        # 处罚 -> -1; (−1*20) = −20 falls in the negative band.
        block = score_news(
            [{"title": "公司公告遭证监会处罚", "published": "2026-09-24 10:00:00"}],
            now=date(2026, 9, 24),
        )
        assert block["score"] == -20
        assert block["sentiment"] == "negative"

    def test_ashare_specific_words_fire(self) -> None:
        # 涨停/跌停/破发/增持/减持 are A-share-native vocabulary with no
        # English equivalent — they must pull their own weight.
        up = score_news([{"title": "一字涨停"}], now=date(2026, 9, 24))
        down = score_news([{"title": "开盘跌停"}], now=date(2026, 9, 24))
        broken = score_news([{"title": "次新股破发"}], now=date(2026, 9, 24))

        assert up["score"] > 0
        assert down["score"] < 0
        assert broken["score"] < 0

    def test_mixed_language_feed_aggregates(self) -> None:
        block = score_news(
            [
                {"title": "Company profit surges to record high", "published": "2026-09-24"},
                {"title": "公司产品价格上调，利好业绩", "published": "2026-09-24"},
            ],
            now=date(2026, 9, 24),
        )
        # English +2 (profit/surge/record/high...) and Chinese +2 (上调/利好)
        # — both articles analyzed, weights 1.0 (same-day publishes).
        assert block["article_count"] == 2
        assert block["score"] > 0

    def test_english_articles_unchanged_by_chinese_lists(self) -> None:
        # Chinese words cannot match ASCII text — the English path is
        # byte-identical to before the bilingual lists existed.
        block = score_news(
            [{"title": "Company profit surges", "published": "2026-09-24"}],
            now=date(2026, 9, 24),
        )
        assert block["score"] == 40  # profit + surge = +2 -> *20

    def test_chinese_headline_without_keywords_counts_as_neutral(self) -> None:
        # No keyword hit -> article not analyzed (same as English "the").
        block = score_news([{"title": "公司召开股东大会"}], now=date(2026, 9, 24))
        assert block["article_count"] == 0
        assert block["score"] == 0
        assert block["sentiment"] == "neutral"


class TestEastMoneyDateFormat:
    def test_space_separated_datetime_parses(self) -> None:
        # East Money serves "YYYY-MM-DD HH:MM:SS"; fromisoformat accepts the
        # space separator and recency decay gets a real date to work with.
        parsed = parse_published("2026-09-24 21:35:00")
        assert parsed == date(2026, 9, 24)

    def test_cn_date_drives_recency(self) -> None:
        fresh = score_news(
            [{"title": "利好", "published": "2026-09-24 21:35:00"}], now=date(2026, 9, 24)
        )
        stale = score_news(
            [{"title": "利好", "published": "2026-09-10 21:35:00"}], now=date(2026, 9, 24)
        )
        # 14-day half-life: the stale copy weighs exactly half.
        assert fresh["score"] == 20
        assert stale["score"] == 10

    def test_malformed_cn_date_keeps_full_weight(self) -> None:
        # Unparseable publishes degrade to full weight, not an error.
        block = score_news([{"title": "利好", "published": "今天上午"}], now=date(2026, 9, 24))
        assert block["score"] == 20
