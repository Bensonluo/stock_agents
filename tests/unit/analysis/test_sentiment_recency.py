"""Recency weighting in news sentiment (14-day half-life).

Equal-weight scoring let a two-year-old press release vote as loudly as
today's headline; these tests pin the decay math and the backwards
compatibility for articles without publish dates.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.analysis.sentiment import parse_published, recency_weight, score_news

NOW = date(2026, 9, 24)


def _article(title: str, published) -> dict:
    return {"title": title, "summary": "", "published": published}


class TestParsePublished:
    def test_iso_string_with_z_suffix(self):
        assert parse_published("2026-09-24T14:30:00Z") == NOW

    def test_plain_date(self):
        assert parse_published("2026-09-24") == NOW

    def test_epoch_int(self):
        assert parse_published(1760000000) == datetime.fromtimestamp(1760000000, tz=UTC).date()

    def test_digit_string_epoch(self):
        assert parse_published("1760000000") == datetime.fromtimestamp(1760000000, tz=UTC).date()

    def test_garbage_and_none(self):
        assert parse_published("not a date") is None
        assert parse_published(None) is None
        assert parse_published([1]) is None


class TestRecencyWeight:
    def test_today_is_full_weight(self):
        assert recency_weight(NOW, now=NOW) == 1.0

    def test_half_life_is_14_days(self):
        assert recency_weight(NOW - timedelta(days=14), now=NOW) == pytest.approx(0.5)

    def test_two_half_lives(self):
        assert recency_weight(NOW - timedelta(days=28), now=NOW) == pytest.approx(0.25)

    def test_unknown_date_keeps_full_weight(self):
        assert recency_weight(None, now=NOW) == 1.0

    def test_future_clamps_to_full(self):
        assert recency_weight(NOW + timedelta(days=3), now=NOW) == 1.0


class TestScoreNewsRecency:
    # "record growth and surge" = +3 keywords; "plunge and loss" = -2
    # (careful: "profit" is a POSITIVE word, so it must stay out of the
    # negative headline).

    def test_same_day_news_reproduces_equal_weight_mean(self):
        result = score_news([_article("record growth and surge", "2026-09-24")], now=NOW)

        assert result["score"] == 60  # +3 keywords * 20, undamped

    def test_stale_only_feed_dilutes_toward_neutral(self):
        fresh = score_news([_article("record growth and surge", "2026-09-24")], now=NOW)
        stale = score_news([_article("record growth and surge", "2025-01-01")], now=NOW)

        assert fresh["score"] == 60
        assert 0 < stale["score"] < 5  # ~21 months old: heavily damped
        assert stale["sentiment"] == "neutral"

    def test_fresh_negative_outweighs_stale_positive(self):
        result = score_news(
            [
                _article("plunge and loss", "2026-09-24"),
                _article("record growth and surge", "2025-01-01"),
            ],
            now=NOW,
        )

        assert result["score"] < 0  # recency tips the mix negative

    def test_unknown_dates_keep_equal_weight(self):
        result = score_news(
            [
                _article("record growth", None),  # +2
                _article("plunge and loss", None),  # -2
            ],
            now=NOW,
        )

        assert result["score"] == 0  # symmetric without dates (back-compat)

    def test_article_count_reports_raw_analyzed_articles(self):
        result = score_news(
            [
                _article("record growth and surge", "2026-09-24"),
                _article("plunge and loss", "2025-01-01"),
            ],
            now=NOW,
        )

        assert result["article_count"] == 2
        assert result["recent_scores"] == [3, -2]
