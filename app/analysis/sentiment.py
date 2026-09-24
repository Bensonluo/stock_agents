"""Canonical news-sentiment scoring (V2 plan §5.1 — one implementation for pipeline and ReAct).

Keyword-count scoring over news headlines/summaries with normalization, trend
and cross-symbol aggregation. Articles are weighted by recency (14-day
half-life): equal-weight scoring let a two-year-old press release vote as
loudly as today's headline. An opt-in LLM layer (llm_sentiment_enabled)
replaces the keyword count with semantic per-article scores in the same
units — the keyword scorer stays as the deterministic floor.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.utils.llm_json import ainvoke_json
from app.utils.logging import get_logger

logger = get_logger(__name__)

POSITIVE_WORDS = {
    "up",
    "rise",
    "gain",
    "growth",
    "strong",
    "beat",
    "top",
    "best",
    "surge",
    "rally",
    "bull",
    "buy",
    "outperform",
    "upgrade",
    "profit",
    "record",
    "high",
    "breakthrough",
    "expansion",
    "dividend",
    "success",
}

NEGATIVE_WORDS = {
    "down",
    "fall",
    "drop",
    "loss",
    "weak",
    "miss",
    "bottom",
    "worst",
    "plunge",
    "crash",
    "bear",
    "sell",
    "underperform",
    "downgrade",
    "debt",
    "low",
    "cut",
    "reduction",
    "layoff",
    "lawsuit",
    "fraud",
    "risk",
}


def empty_sentiment() -> dict[str, Any]:
    return {
        "sentiment": "neutral",
        "score": 0,
        "article_count": 0,
        "recent_scores": [],
        "trend": "no_data",
    }


def parse_published(value: Any) -> date | None:
    """Best-effort article publish date: ISO string or unix seconds.

    yfinance serves both shapes (content.pubDate ISO strings, legacy
    providerPublishTime epoch ints); anything unparseable yields None so
    callers can fall back to full recency weight.
    """
    if value is None:
        return None
    if isinstance(value, int | float):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC).date()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            try:
                return datetime.fromtimestamp(float(text), tz=UTC).date()
            except (OverflowError, OSError, ValueError):
                return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def recency_weight(published: date | None, *, now: date | None = None) -> float:
    """Time-decay weight for an article: 14-day half-life.

    Unknown publish dates keep full weight — better to trust the article
    than to assume it is ancient. Future dates clamp to 1.0.
    """
    if published is None:
        return 1.0
    reference = now or datetime.now(UTC).date()
    age_days = max(0, (reference - published).days)
    return 0.5 ** (age_days / 14.0)


def score_news(
    news: list[dict[str, Any]],
    *,
    now: date | None = None,
    article_scores: list[int] | None = None,
) -> dict[str, Any]:
    """Score one symbol's news list into the canonical per-symbol block.

    Each article's score enters the sum scaled by its recency weight (see
    recency_weight), divided by the raw article count: fresh news reproduces
    the old equal-weight mean exactly, while stale-only feeds dilute toward
    neutral instead of shouting as today's view.

    ``article_scores`` replaces keyword counting with precomputed per-article
    scores in the same -5..+5 units (e.g. from the LLM semantic scorer).
    Every article then counts as analyzed — a semantic 0 is information, not
    an absence — and the block carries ``"scoring": "llm_semantic"`` so
    provenance stays inspectable. Without it the output is byte-identical to
    the pure keyword path.
    """
    total_score = 0.0
    analyzed_count = 0
    recent_scores: list[int] = []

    for index, article in enumerate(news):
        if article_scores is not None:
            score = int(article_scores[index])
        else:
            text = (article.get("title", "") + " " + article.get("summary", "")).lower()
            score = sum(1 for word in POSITIVE_WORDS if word in text) - sum(
                1 for word in NEGATIVE_WORDS if word in text
            )
        if article_scores is not None or score != 0:
            weight = recency_weight(parse_published(article.get("published")), now=now)
            total_score += score * weight
            analyzed_count += 1
            recent_scores.append(score)

    normalized = (
        max(-100, min(100, (total_score / analyzed_count) * 20)) if analyzed_count > 0 else 0
    )
    if normalized >= 40:
        sentiment = "very_positive"
    elif normalized >= 15:
        sentiment = "positive"
    elif normalized <= -40:
        sentiment = "very_negative"
    elif normalized <= -15:
        sentiment = "negative"
    else:
        sentiment = "neutral"

    block = {
        "sentiment": sentiment,
        "score": normalized,
        "article_count": analyzed_count,
        "recent_scores": recent_scores[-10:],
        "trend": calculate_trend(recent_scores),
    }
    if article_scores is not None:
        block["scoring"] = "llm_semantic"
    return block


# ----------------------------------------------------------------------
# LLM semantic scoring (opt-in): per-article scores in keyword units.
# ----------------------------------------------------------------------

# Beyond this many headlines one LLM call stops being reliable (or cheap).
_LLM_SCORE_MAX_ARTICLES = 30
_LLM_SCORE_RANGE = 5
_LLM_SCORE_TIMEOUT_SECONDS = 20.0


class _LlmArticleScores(BaseModel):
    """Contract for the per-headline LLM scores (validated on both paths)."""

    scores: list[int] = Field(description="One integer score per headline, -5..+5")


def _headline_lines(news: list[dict[str, Any]]) -> list[str]:
    """Numbered headline + truncated summary, one line per article."""
    lines: list[str] = []
    for i, article in enumerate(news, start=1):
        title = (article.get("title") or "").strip()
        summary = (article.get("summary") or "").strip()[:160]
        lines.append(f"{i}. {title} — {summary}" if summary else f"{i}. {title}")
    return lines


async def llm_article_scores(news: list[dict[str, Any]], llm: Any) -> list[int] | None:
    """Per-article semantic scores on the keyword scale (-5..+5), or None.

    One call scores every headline. Any failure — wrong count, out-of-range
    value, unparsable output, transport error, timeout — degrades to None so
    callers keep the deterministic keyword scorer as the floor.
    """
    if not news or llm is None or len(news) > _LLM_SCORE_MAX_ARTICLES:
        return None
    try:
        parsed = await asyncio.wait_for(
            ainvoke_json(
                llm,
                system=(
                    "You are a financial news sentiment scorer. For each numbered "
                    "headline, score the stock's sentiment from -5 (strongly bearish) "
                    "to +5 (strongly bullish); 0 means neutral or irrelevant to the "
                    'stock. Respond only with JSON: {"scores": [integer, ...]} with '
                    "exactly one score per headline, in order."
                ),
                user="\n".join(_headline_lines(news)),
                schema=_LlmArticleScores,
            ),
            timeout=_LLM_SCORE_TIMEOUT_SECONDS,
        )
    except Exception as e:  # noqa: BLE001 - degrade by design
        logger.warning(f"LLM sentiment scoring unavailable: {e}")
        return None
    scores = (parsed or {}).get("scores")
    if not isinstance(scores, list) or len(scores) != len(news):
        logger.warning("LLM sentiment scores malformed (count); falling back to keywords")
        return None
    if any(not isinstance(s, int) or s < -_LLM_SCORE_RANGE or s > _LLM_SCORE_RANGE for s in scores):
        logger.warning("LLM sentiment scores malformed (range); falling back to keywords")
        return None
    return scores


async def score_news_with_llm(
    news: list[dict[str, Any]], llm: Any, *, now: date | None = None
) -> dict[str, Any]:
    """Canonical block with LLM semantic per-article scores when available.

    Flag/LLM gating lives with the caller (see SentimentAnalysisAgent);
    this function only decides semantic-vs-keyword and never raises.
    """
    scores = await llm_article_scores(news, llm)
    if scores is None:
        return score_news(news, now=now)
    return score_news(news, now=now, article_scores=scores)


def calculate_trend(scores: list[float]) -> str:
    if len(scores) < 3:
        return "insufficient_data"
    recent = scores[-3:]
    if all(s > 0 for s in recent):
        return "improving"
    if all(s < 0 for s in recent):
        return "declining"
    if recent[-1] > recent[0]:
        return "improving"
    if recent[-1] < recent[0]:
        return "declining"
    return "stable"


def calculate_overall(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {"sentiment": "neutral", "score": 0}
    scores = [r.get("score", 0) for r in results.values()]
    avg = sum(scores) / len(scores) if scores else 0
    if avg >= 30:
        sentiment = "positive"
    elif avg <= -30:
        sentiment = "negative"
    else:
        sentiment = "neutral"
    return {
        "sentiment": sentiment,
        "score": avg,
        "positive_count": sum(1 for s in results.values() if s.get("score", 0) > 15),
        "negative_count": sum(1 for s in results.values() if s.get("score", 0) < -15),
        "neutral_count": sum(1 for s in results.values() if -15 <= s.get("score", 0) <= 15),
    }
