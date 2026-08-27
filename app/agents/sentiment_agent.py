"""Sentiment analysis agent for news and social sentiment."""

from datetime import datetime
from typing import Any

from app.agents.base import StatelessAgent
from app.analysis.sentiment import calculate_overall, calculate_trend, empty_sentiment, score_news
from app.orchestration.state import AgentState
from app.utils.logging import get_logger

logger = get_logger(__name__)


class SentimentAnalysisAgent(StatelessAgent):
    """Agent responsible for sentiment analysis of news and social data.

    This agent:
    - Analyzes news sentiment
    - Aggregates sentiment across sources
    - Identifies sentiment trends
    - Flags significant news events

    Can use LLM for more sophisticated sentiment analysis.
    """

    async def process(self, state: AgentState) -> dict[str, Any]:
        """Process sentiment analysis.

        Args:
            state: Current agent state

        Returns:
            Dictionary containing sentiment analysis results
        """
        news_data = state.get("news_data", [])
        symbols = state.get("symbols", [])

        if not news_data and not symbols:
            logger.warning("No data available for sentiment analysis")
            return {}

        logger.info(f"Analyzing sentiment for {len(symbols)} symbols with {len(news_data)} news items")

        results = {}

        for i, symbol in enumerate(symbols):
            # Get news for this symbol - check both original symbol and related_symbols
            symbol_news = []
            for n in news_data:
                # Check if news is related to this symbol
                related = n.get("related_symbols", [])
                original = n.get("original_symbol", "")

                # Include if symbol is in related_symbols or if original_symbol matches
                # Also include news for the first symbol as fallback if we have limited news
                if symbol in related or original == symbol or (i == 0 and not symbol_news and len(news_data) > 0):
                    symbol_news.append(n)

            if not symbol_news:
                logger.warning(f"No news found for {symbol}, using neutral sentiment")
                results[symbol] = self._empty_sentiment()
                continue

            # Analyze sentiment
            sentiment = await self._analyze_news_sentiment(symbol_news)

            # Use LLM for deeper analysis if available
            if self.llm and symbol_news:
                llm_sentiment = await self._llm_sentiment_analysis(symbol, symbol_news[:5])
                sentiment["llm_analysis"] = llm_sentiment

            results[symbol] = sentiment

        return {
            "sentiment_by_symbol": results,
            "overall_sentiment": self._calculate_overall_sentiment(results),
            "overall": self._calculate_overall_sentiment(results),  # Add 'overall' key for frontend compatibility
            "timestamp": datetime.now().isoformat(),
        }

    async def _analyze_news_sentiment(self, news: list[dict]) -> dict[str, Any]:
        """Score one symbol's news via the canonical sentiment module."""
        return score_news(news)

    async def _llm_sentiment_analysis(self, symbol: str, news: list[dict]) -> dict[str, Any]:
        """Use LLM for deeper sentiment analysis.

        Args:
            symbol: Stock symbol
            news: List of news articles

        Returns:
            LLM analysis results
        """
        try:
            # Prepare news summary
            news_text = "\n".join([
                f"- {n.get('title', '')}: {n.get('summary', n.get('title', ''))[:200]}"
                for n in news[:5]
            ])

            prompt = f"""Analyze the sentiment for {symbol} based on these recent news headlines:

{news_text}

Provide a JSON response with:
- overall_sentiment: "positive", "negative", or "neutral"
- confidence: score from 0-100
- key_factors: list of main factors influencing sentiment
- summary: brief 1-2 sentence summary

Respond only with valid JSON."""

            response = await self.invoke_llm(prompt)

            # Try to parse JSON from response
            import json
            try:
                # Extract JSON from response
                start = response.find("{")
                end = response.rfind("}") + 1
                if start >= 0 and end > start:
                    json_str = response[start:end]
                    return json.loads(json_str)
            except json.JSONDecodeError:
                pass

            # Fallback: simple text analysis
            return {
                "overall_sentiment": "neutral",
                "confidence": 50,
                "summary": response[:200],
            }

        except Exception as e:
            logger.error(f"LLM sentiment analysis failed: {e}")
            return {}

    def _calculate_sentiment_trend(self, scores: list[float]) -> str:
        return calculate_trend(scores)

    def _calculate_overall_sentiment(self, results: dict[str, dict]) -> dict[str, Any]:
        return calculate_overall(results)

    def _empty_sentiment(self) -> dict[str, Any]:
        return empty_sentiment()
