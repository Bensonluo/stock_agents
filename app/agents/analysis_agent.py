"""Analysis agent for technical and fundamental analysis."""

from datetime import datetime
from typing import Any

import pandas as pd

from app.agents.base import BaseAgent
from app.analysis.fundamental import financial_quality
from app.analysis.fundamental.scoring import (
    _analyze_growth,
    _analyze_profitability,
    _calculate_overall_score,
    _recommendation,
    analyze_fundamental_scoring,
)
from app.analysis.technical import analyze_daily, to_dataframe, weekly_sma_summary
from app.analysis.valuation import scenario_valuation
from app.orchestration.state import AgentState
from app.utils.logging import get_logger

logger = get_logger(__name__)


class TechnicalAnalysisAgent(BaseAgent):
    """Agent responsible for technical analysis of stock data.

    This agent:
    - Calculates technical indicators (MA, EMA, RSI, MACD, Bollinger Bands)
    - Identifies chart patterns
    - Generates trading signals based on technical analysis
    - Provides support and resistance levels

    Uses pandas-ta for comprehensive indicator calculations.
    """

    async def execute(self, state: AgentState) -> dict[str, Any]:
        """Execute the technical analysis agent.

        Args:
            state: Current agent state

        Returns:
            Partial state with technical analysis results only
        """
        market_data = state.get("market_data", {})

        if not market_data:
            logger.warning("No market data available for technical analysis")
            return {"technical_analysis": {}}

        logger.info(f"Performing technical analysis for {len(market_data)} symbols")

        results = {}

        for symbol, data in market_data.items():
            try:
                analysis = await self._analyze_symbol(symbol, data)
                if analysis:
                    results[symbol] = analysis
            except Exception as e:
                logger.error(f"Error analyzing {symbol}: {e}")

        logger.info(f"Completed technical analysis for {len(results)} symbols")

        # Return only the partial state (field we modify)
        return {"technical_analysis": results}

    async def _analyze_symbol(self, symbol: str, data: dict) -> dict[str, Any]:
        """Perform technical analysis for a single symbol via the daily engine.

        Args:
            symbol: Stock symbol
            data: Market data dictionary

        Returns:
            Dictionary containing technical analysis results
        """
        hist_data = data.get("historical_data")
        if not hist_data:
            return {}

        analysis = analyze_daily(
            hist_data,
            symbol=symbol,
            current_price=data.get("current_price"),
            source="market_data_history",
        )
        if analysis.get("status") != "available":
            logger.warning(f"Insufficient data for {symbol}: {analysis.get('reason')}")
            return analysis

        df = to_dataframe(hist_data)
        analysis["patterns"] = self._detect_patterns(df)
        analysis["weekly_sma"] = self._weekly_sma_pack(symbol, hist_data)
        analysis["timestamp"] = datetime.now().isoformat()
        return analysis

    def _weekly_sma_pack(self, symbol: str, hist_data: dict) -> dict[str, Any]:
        """Weekly SMA evidence pack; failure must not sink the whole analysis."""
        try:
            return weekly_sma_summary(hist_data, symbol=symbol, source="market_data_history")
        except Exception as e:
            logger.warning(f"Weekly SMA pack failed for {symbol}: {e}")
            return {"status": "error", "reason": str(e)}

    def _detect_patterns(self, df: pd.DataFrame) -> dict[str, Any]:
        """Detect common candlestick patterns.

        Args:
            df: Price DataFrame

        Returns:
            Dictionary of detected patterns
        """
        patterns = {}

        if len(df) < 3:
            return patterns

        # Get recent candles
        recent = df.tail(5).to_dict("records")

        # Simple pattern detection
        latest = recent[-1]
        prev = recent[-2]

        # Doji (open ≈ close)
        body_size = abs(latest["close"] - latest["open"])
        range_size = latest["high"] - latest["low"]
        if range_size > 0 and body_size / range_size < 0.1:
            patterns["doji"] = True

        # Hammer (small body, long lower shadow)
        lower_shadow = (
            latest["close"] - latest["low"]
            if latest["close"] > latest["open"]
            else latest["open"] - latest["low"]
        )
        upper_shadow = latest["high"] - max(latest["open"], latest["close"])
        if lower_shadow > body_size * 2 and upper_shadow < body_size * 0.5:
            patterns["hammer"] = True

        # Engulfing patterns
        prev_body = abs(prev["close"] - prev["open"])
        curr_body = abs(latest["close"] - latest["open"])

        if curr_body > prev_body * 1.2:
            if (
                prev["close"] > prev["open"]  # Previous was bullish
                and latest["close"] < latest["open"]  # Current is bearish
                and latest["open"] > prev["close"]
                and latest["close"] < prev["open"]
            ):
                patterns["bearish_engulfing"] = True

            elif (
                prev["close"] < prev["open"]  # Previous was bearish
                and latest["close"] > latest["open"]  # Current is bullish
                and latest["open"] < prev["close"]
                and latest["close"] > prev["open"]
            ):
                patterns["bullish_engulfing"] = True

        return patterns


class FundamentalAnalysisAgent(BaseAgent):
    """Agent responsible for fundamental analysis of stocks.

    This agent:
    - Analyzes financial statements
    - Calculates valuation metrics
    - Compares with industry averages
    - Evaluates financial health
    - Assesses growth potential
    """

    async def execute(self, state: AgentState) -> dict[str, Any]:
        """Execute the fundamental analysis agent.

        Args:
            state: Current agent state

        Returns:
            Partial state with fundamental analysis results only
        """
        financial_data = state.get("financial_data", {})
        market_data = state.get("market_data", {})

        if not financial_data:
            logger.warning("No financial data available for fundamental analysis")
            return {"fundamental_analysis": {}}

        logger.info(f"Performing fundamental analysis for {len(financial_data)} symbols")

        results = {}

        for symbol in financial_data:
            try:
                fin_data = financial_data.get(symbol, {})
                mkt_data = market_data.get(symbol, {})

                analysis = await self._analyze_fundamentals(symbol, fin_data, mkt_data)
                if analysis:
                    results[symbol] = analysis
            except Exception as e:
                logger.error(f"Error analyzing fundamentals for {symbol}: {e}")

        logger.info(f"Completed fundamental analysis for {len(results)} symbols")

        # Return only the partial state (field we modify)
        return {"fundamental_analysis": results}

    async def _analyze_fundamentals(
        self, symbol: str, fin_data: dict, mkt_data: dict
    ) -> dict[str, Any]:
        """Fundamental analysis via the canonical scoring module."""
        result = analyze_fundamental_scoring({symbol: fin_data}, mkt_data).get(symbol) or {}
        return {
            **result,
            "quality": self._financial_quality(symbol, fin_data),
            "valuation_scenarios": self._valuation_scenarios(symbol, fin_data, mkt_data),
            "timestamp": datetime.now().isoformat(),
        }

    def _analyze_profitability(self, metrics: dict) -> dict[str, Any]:
        return _analyze_profitability(metrics)

    def _analyze_growth(self, fin_data: dict) -> dict[str, Any]:
        return _analyze_growth(fin_data)

    def _calculate_overall_score(self, *args, **kwargs) -> dict[str, Any]:
        return _calculate_overall_score(*args, **kwargs)

    def _generate_recommendation(self, overall_score) -> str:
        return _recommendation(
            overall_score["score"] if isinstance(overall_score, dict) else overall_score
        )

    def _financial_quality(self, symbol: str, fin_data: dict) -> dict[str, Any]:
        """Statement-based quality/trend/red-flag summary from the engine."""
        try:
            return financial_quality(fin_data, symbol=symbol, source="financial_statements")
        except Exception as e:
            logger.warning(f"Financial quality engine failed for {symbol}: {e}")
            return {"status": "error", "reason": str(e)}

    def _valuation_scenarios(self, symbol: str, fin_data: dict, mkt_data: dict) -> dict[str, Any]:
        """Bear/Base/Bull valuation range from the engine."""
        metrics = fin_data.get("metrics", {})
        try:
            return scenario_valuation(
                symbol=symbol,
                current_price=mkt_data.get("current_price"),
                trailing_eps=metrics.get("trailing_eps"),
                ps_ratio=metrics.get("ps_ratio"),
                earnings_growth=metrics.get("earnings_growth"),
                revenue_growth=metrics.get("revenue_growth"),
                source="financial_metrics",
            )
        except Exception as e:
            logger.warning(f"Valuation engine failed for {symbol}: {e}")
            return {"status": "error", "reason": str(e)}
