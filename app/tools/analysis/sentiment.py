"""Sentiment analysis tools. Extracted from app/agents/sentiment_agent.py"""

from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.utils.logging import get_logger

logger = get_logger(__name__)

POSITIVE_WORDS = {
    "up", "rise", "gain", "growth", "strong", "beat", "top", "best",
    "surge", "rally", "bull", "buy", "outperform", "upgrade", "profit",
    "record", "high", "breakthrough", "expansion", "dividend", "success",
}

NEGATIVE_WORDS = {
    "down", "fall", "drop", "loss", "weak", "miss", "bottom", "worst",
    "plunge", "crash", "bear", "sell", "underperform", "downgrade", "debt",
    "low", "cut", "reduction", "layoff", "lawsuit", "fraud", "risk",
}


class AnalyzeSentimentInput(BaseModel):
    news_data: list = Field(description="News articles from fetch_stock_data")
    symbols: list[str] = Field(description="Stock symbols to analyze")


@tool(args_schema=AnalyzeSentimentInput)
def analyze_sentiment(news_data: list, symbols: list[str]) -> dict[str, Any]:
    """Assess market sentiment from recent news."""
    results = {}

    for symbol in symbols:
        symbol_news = [
            n for n in news_data
            if symbol in n.get("related_symbols", []) or n.get("original_symbol") == symbol
        ]
        if not symbol_news:
            results[symbol] = _empty_sentiment()
            continue

        total_score, analyzed, recent_scores = 0, 0, []
        for article in symbol_news:
            text = (article.get("title", "") + " " + article.get("summary", "")).lower()
            score = sum(1 for w in POSITIVE_WORDS if w in text) - sum(1 for w in NEGATIVE_WORDS if w in text)
            if score != 0:
                total_score += score
                analyzed += 1
                recent_scores.append(score)

        normalized = max(-100, min(100, (total_score / analyzed) * 20)) if analyzed > 0 else 0
        if normalized >= 40: sentiment = "very_positive"
        elif normalized >= 15: sentiment = "positive"
        elif normalized <= -40: sentiment = "very_negative"
        elif normalized <= -15: sentiment = "negative"
        else: sentiment = "neutral"

        results[symbol] = {
            "sentiment": sentiment,
            "score": normalized,
            "article_count": analyzed,
            "recent_scores": recent_scores[-10:],
            "trend": _calculate_trend(recent_scores),
        }

    return {"sentiment_by_symbol": results, "overall_sentiment": _calculate_overall(results)}


def _empty_sentiment() -> dict:
    return {"sentiment": "neutral", "score": 0, "article_count": 0, "recent_scores": [], "trend": "no_data"}


def _calculate_trend(scores: list) -> str:
    if len(scores) < 3:
        return "insufficient_data"
    recent = scores[-3:]
    if all(s > 0 for s in recent): return "improving"
    elif all(s < 0 for s in recent): return "declining"
    elif recent[-1] > recent[0]: return "improving"
    elif recent[-1] < recent[0]: return "declining"
    else: return "stable"


def _calculate_overall(results: dict) -> dict:
    if not results:
        return {"sentiment": "neutral", "score": 0}
    scores = [r.get("score", 0) for r in results.values()]
    avg = sum(scores) / len(scores) if scores else 0
    if avg >= 30: sentiment = "positive"
    elif avg <= -30: sentiment = "negative"
    else: sentiment = "neutral"
    return {
        "sentiment": sentiment,
        "score": avg,
        "positive_count": sum(1 for s in results.values() if s.get("score", 0) > 15),
        "negative_count": sum(1 for s in results.values() if s.get("score", 0) < -15),
        "neutral_count": sum(1 for s in results.values() if -15 <= s.get("score", 0) <= 15),
    }
