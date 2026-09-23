"""Canonical news-sentiment scoring (V2 plan §5.1 — one implementation for pipeline and ReAct).

Keyword-count scoring over news headlines/summaries with normalization, trend
and cross-symbol aggregation. This is deliberately simple lexicon scoring;
entity linking, decay and event classification arrive with Phase 4 data.
"""

from __future__ import annotations

from typing import Any

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


def score_news(news: list[dict[str, Any]]) -> dict[str, Any]:
    """Score one symbol's news list into the canonical per-symbol block."""
    total_score = 0
    analyzed_count = 0
    recent_scores: list[int] = []

    for article in news:
        text = (article.get("title", "") + " " + article.get("summary", "")).lower()
        score = sum(1 for word in POSITIVE_WORDS if word in text) - sum(
            1 for word in NEGATIVE_WORDS if word in text
        )
        if score != 0:
            total_score += score
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

    return {
        "sentiment": sentiment,
        "score": normalized,
        "article_count": analyzed_count,
        "recent_scores": recent_scores[-10:],
        "trend": calculate_trend(recent_scores),
    }


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
