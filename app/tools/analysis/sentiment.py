"""Sentiment analysis tool over the canonical scoring module."""

from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.analysis.sentiment import (
    NEGATIVE_WORDS,
    POSITIVE_WORDS,
    calculate_overall,
    calculate_trend,
    empty_sentiment,
    score_news,
)

# Backwards-compatible aliases for callers importing the historical names.
_empty_sentiment = empty_sentiment
_calculate_trend = calculate_trend
_calculate_overall = calculate_overall

__all__ = ["NEGATIVE_WORDS", "POSITIVE_WORDS", "analyze_sentiment"]


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
        results[symbol] = score_news(symbol_news) if symbol_news else empty_sentiment()

    return {"sentiment_by_symbol": results, "overall_sentiment": calculate_overall(results)}
