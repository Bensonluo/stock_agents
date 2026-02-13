"""Sentiment analysis agent for news and social sentiment."""

from datetime import datetime
from typing import Any, Dict, List

from app.agents.base import StatelessAgent
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

    async def process(self, state: AgentState) -> Dict[str, Any]:
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

    async def _analyze_news_sentiment(self, news: List[Dict]) -> Dict[str, Any]:
        """Analyze sentiment from news headlines and summaries.

        Args:
            news: List of news articles

        Returns:
            Sentiment analysis dictionary
        """
        positive_words = {
            "up", "rise", "gain", "growth", "strong", "beat", "top", "best",
            "surge", "rally", "bull", "buy", "outperform", "upgrade", "profit",
            "record", "high", "breakthrough", "expansion", "dividend", "success",
        }

        negative_words = {
            "down", "fall", "drop", "loss", "weak", "miss", "bottom", "worst",
            "plunge", "crash", "bear", "sell", "underperform", "downgrade", "debt",
            "low", "cut", "reduction", "layoff", "lawsuit", "fraud", "risk",
        }

        total_score = 0
        analyzed_count = 0
        recent_sentiment = []

        for article in news:
            text = (
                article.get("title", "") + " " +
                article.get("summary", "")
            ).lower()

            score = 0
            for word in positive_words:
                if word in text:
                    score += 1
            for word in negative_words:
                if word in text:
                    score -= 1

            if score != 0:
                total_score += score
                analyzed_count += 1
                recent_sentiment.append(score)

        # Normalize score
        if analyzed_count > 0:
            avg_score = total_score / analyzed_count
            normalized_score = max(-100, min(100, avg_score * 20))
        else:
            avg_score = 0
            normalized_score = 0

        # Determine sentiment
        if normalized_score >= 40:
            sentiment = "very_positive"
        elif normalized_score >= 15:
            sentiment = "positive"
        elif normalized_score <= -40:
            sentiment = "very_negative"
        elif normalized_score <= -15:
            sentiment = "negative"
        else:
            sentiment = "neutral"

        return {
            "sentiment": sentiment,
            "score": normalized_score,
            "article_count": analyzed_count,
            "recent_scores": recent_sentiment[-10:],
            "trend": self._calculate_sentiment_trend(recent_sentiment),
        }

    async def _llm_sentiment_analysis(self, symbol: str, news: List[Dict]) -> Dict[str, Any]:
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

    def _calculate_sentiment_trend(self, scores: List[float]) -> str:
        """Calculate sentiment trend from recent scores.

        Args:
            scores: List of recent sentiment scores

        Returns:
            Trend string
        """
        if len(scores) < 3:
            return "insufficient_data"

        recent = scores[-3:]
        if all(s > 0 for s in recent):
            return "improving"
        elif all(s < 0 for s in recent):
            return "declining"
        elif recent[-1] > recent[0]:
            return "improving"
        elif recent[-1] < recent[0]:
            return "declining"
        else:
            return "stable"

    def _calculate_overall_sentiment(self, results: Dict[str, Dict]) -> Dict[str, Any]:
        """Calculate overall sentiment across all symbols.

        Args:
            results: Sentiment results by symbol

        Returns:
            Overall sentiment summary
        """
        if not results:
            return {"sentiment": "neutral", "score": 0}

        scores = [r.get("score", 0) for r in results.values()]
        avg_score = sum(scores) / len(scores) if scores else 0

        if avg_score >= 30:
            sentiment = "positive"
        elif avg_score <= -30:
            sentiment = "negative"
        else:
            sentiment = "neutral"

        return {
            "sentiment": sentiment,
            "score": avg_score,
            "positive_count": sum(1 for s in results.values() if s.get("score", 0) > 15),
            "negative_count": sum(1 for s in results.values() if s.get("score", 0) < -15),
            "neutral_count": sum(1 for s in results.values() if -15 <= s.get("score", 0) <= 15),
        }

    def _empty_sentiment(self) -> Dict[str, Any]:
        """Return empty sentiment result.

        Returns:
            Empty sentiment dictionary
        """
        return {
            "sentiment": "neutral",
            "score": 0,
            "article_count": 0,
            "recent_scores": [],
            "trend": "no_data",
        }
