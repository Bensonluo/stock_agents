"""Analysis agent for technical and fundamental analysis."""

from datetime import datetime
from typing import Any

import pandas as pd

from app.agents.base import BaseAgent
from app.analysis.fundamental import financial_quality
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
        lower_shadow = latest["close"] - latest["low"] if latest["close"] > latest["open"] else latest["open"] - latest["low"]
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
        """Perform fundamental analysis for a single symbol.

        Args:
            symbol: Stock symbol
            fin_data: Financial data dictionary
            mkt_data: Market data dictionary

        Returns:
            Dictionary containing fundamental analysis results
        """
        metrics = fin_data.get("metrics", {})

        # Analyze profitability
        profitability = self._analyze_profitability(metrics)

        # Analyze valuation
        valuation = self._analyze_valuation(metrics, mkt_data)

        # Analyze financial health
        health = self._analyze_financial_health(metrics)

        # Analyze growth
        growth = self._analyze_growth(fin_data)

        # Calculate overall score
        overall_score = self._calculate_overall_score(
            profitability, valuation, health, growth
        )

        # Generate recommendation
        recommendation = self._generate_recommendation(overall_score)

        return {
            "symbol": symbol,
            "profitability": profitability,
            "valuation": valuation,
            "financial_health": health,
            "growth": growth,
            "overall_score": overall_score,
            "recommendation": recommendation,
            "quality": self._financial_quality(symbol, fin_data),
            "valuation_scenarios": self._valuation_scenarios(symbol, fin_data, mkt_data),
            "timestamp": datetime.now().isoformat(),
        }

    def _financial_quality(self, symbol: str, fin_data: dict) -> dict[str, Any]:
        """Statement-based quality/trend/red-flag summary from the engine."""
        try:
            return financial_quality(fin_data, symbol=symbol, source="financial_statements")
        except Exception as e:
            logger.warning(f"Financial quality engine failed for {symbol}: {e}")
            return {"status": "error", "reason": str(e)}

    def _valuation_scenarios(
        self, symbol: str, fin_data: dict, mkt_data: dict
    ) -> dict[str, Any]:
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

    def _analyze_profitability(self, metrics: dict) -> dict[str, Any]:
        """Analyze profitability metrics.

        Args:
            metrics: Financial metrics dictionary

        Returns:
            Profitability analysis
        """
        roe = metrics.get("roe")
        roa = metrics.get("roa")
        profit_margin = metrics.get("profit_margin")
        operating_margin = metrics.get("operating_margin")

        score = 0
        details = {}

        # ROE analysis (0-40 points)
        if roe is not None:
            details["roe"] = float(roe)
            if roe >= 0.20:
                score += 40
            elif roe >= 0.15:
                score += 30
            elif roe >= 0.10:
                score += 20
            elif roe >= 0.05:
                score += 10

        # ROA analysis (0-20 points)
        if roa is not None:
            details["roa"] = float(roa)
            if roa >= 0.10:
                score += 20
            elif roa >= 0.05:
                score += 15
            elif roa >= 0.02:
                score += 10

        # Profit margin analysis (0-20 points)
        if profit_margin is not None:
            details["profit_margin"] = float(profit_margin)
            if profit_margin >= 0.2:
                score += 20
            elif profit_margin >= 0.1:
                score += 15
            elif profit_margin >= 0.05:
                score += 10

        # Operating margin analysis (0-20 points)
        if operating_margin is not None:
            details["operating_margin"] = float(operating_margin)
            if operating_margin >= 0.15:
                score += 20
            elif operating_margin >= 0.1:
                score += 15
            elif operating_margin >= 0.05:
                score += 10

        return {
            "score": score,
            "rating": self._score_to_rating(score, 100),
            "details": details,
            "status": "available" if details else "insufficient_data",
        }

    def _analyze_valuation(self, metrics: dict, mkt_data: dict) -> dict[str, Any]:
        """Analyze valuation metrics.

        Args:
            metrics: Financial metrics dictionary
            mkt_data: Market data dictionary

        Returns:
            Valuation analysis
        """
        pe = metrics.get("pe_ratio")
        pb = metrics.get("pb_ratio")
        ps = metrics.get("ps_ratio")
        ev_ebitda = metrics.get("ev_ebitda")

        score = 0
        details = {}

        # P/E analysis (0-30 points)
        if pe is not None:
            details["pe_ratio"] = float(pe)
            if 0 < pe <= 15:
                score += 30  # Undervalued
            elif pe <= 25:
                score += 20  # Fair value
            elif pe <= 40:
                score += 10  # Slightly overvalued

        # P/B analysis (0-25 points)
        if pb is not None:
            details["pb_ratio"] = float(pb)
            if 0 < pb <= 1:
                score += 25
            elif pb <= 2:
                score += 20
            elif pb <= 3:
                score += 15

        # P/S analysis (0-25 points)
        if ps is not None:
            details["ps_ratio"] = float(ps)
            if 0 < ps <= 2:
                score += 25
            elif ps <= 4:
                score += 20
            elif ps <= 6:
                score += 15

        # EV/EBITDA analysis (0-20 points)
        if ev_ebitda is not None:
            details["ev_ebitda"] = float(ev_ebitda)
            if 0 < ev_ebitda <= 8:
                score += 20
            elif ev_ebitda <= 12:
                score += 15
            elif ev_ebitda <= 16:
                score += 10

        return {
            "score": score,
            "rating": self._score_to_rating(score, 100),
            "details": details,
            "status": "available" if details else "insufficient_data",
        }

    def _analyze_financial_health(self, metrics: dict) -> dict[str, Any]:
        """Analyze financial health metrics.

        Args:
            metrics: Financial metrics dictionary

        Returns:
            Financial health analysis
        """
        debt_to_equity = metrics.get("debt_to_equity")
        current_ratio = metrics.get("current_ratio")
        quick_ratio = metrics.get("quick_ratio")

        score = 0
        details = {}

        # Debt-to-equity analysis (0-40 points)
        if debt_to_equity is not None:
            details["debt_to_equity"] = float(debt_to_equity)
            if 0 <= debt_to_equity <= 0.5:
                score += 40
            elif debt_to_equity <= 1:
                score += 30
            elif debt_to_equity <= 1.5:
                score += 20
            elif debt_to_equity <= 2:
                score += 10

        # Current ratio analysis (0-30 points)
        if current_ratio is not None:
            details["current_ratio"] = float(current_ratio)
            if current_ratio >= 2:
                score += 30
            elif current_ratio >= 1.5:
                score += 25
            elif current_ratio >= 1:
                score += 15

        # Quick ratio analysis (0-30 points)
        if quick_ratio is not None:
            details["quick_ratio"] = float(quick_ratio)
            if quick_ratio >= 1.5:
                score += 30
            elif quick_ratio >= 1:
                score += 25
            elif quick_ratio >= 0.8:
                score += 15

        return {
            "score": score,
            "rating": self._score_to_rating(score, 100),
            "details": details,
            "status": "available" if details else "insufficient_data",
        }

    def _analyze_growth(self, fin_data: dict) -> dict[str, Any]:
        """Analyze growth metrics.

        Args:
            fin_data: Financial data dictionary

        Returns:
            Growth analysis
        """
        metrics = fin_data.get("metrics", {})
        growth_metrics = {
            "revenue_growth": metrics.get("revenue_growth"),
            "earnings_growth": metrics.get("earnings_growth"),
        }
        available = {key: value for key, value in growth_metrics.items() if value is not None}
        if not available:
            return {
                "score": None,
                "rating": "insufficient_data",
                "status": "insufficient_data",
                "details": {
                    "note": "Growth analysis requires revenue or earnings growth data"
                },
            }

        def score_metric(value: float) -> int:
            if value >= 0.20:
                return 50
            if value >= 0.10:
                return 40
            if value >= 0.05:
                return 30
            if value >= 0:
                return 20
            if value >= -0.10:
                return 10
            return 0

        raw_score = sum(score_metric(float(value)) for value in available.values())
        score = raw_score / (50 * len(available)) * 100
        return {
            "score": round(score, 2),
            "rating": self._score_to_rating(score, 100),
            "status": "available",
            "details": {key: float(value) for key, value in available.items()},
        }

    def _calculate_overall_score(
        self,
        profitability: dict,
        valuation: dict,
        health: dict,
        growth: dict,
    ) -> dict[str, Any]:
        """Calculate overall fundamental score.

        Args:
            profitability: Profitability analysis
            valuation: Valuation analysis
            health: Financial health analysis
            growth: Growth analysis

        Returns:
            Overall score and rating
        """
        # Weighted average
        # Profitability: 35%
        # Valuation: 30%
        # Health: 25%
        # Growth: 10%

        components = {
            "profitability": (profitability, 0.35),
            "valuation": (valuation, 0.30),
            "health": (health, 0.25),
            "growth": (growth, 0.10),
        }
        available = {
            name: (component.get("score"), weight)
            for name, (component, weight) in components.items()
            if component.get("score") is not None
            and component.get("status") != "insufficient_data"
        }
        available_weight = sum(weight for _, weight in available.values())
        component_scores = {
            name: component.get("score") for name, (component, _) in components.items()
        }

        if available_weight == 0:
            return {
                "score": None,
                "components": component_scores,
                "rating": "insufficient_data",
                "status": "insufficient_data",
                "available_weight": 0.0,
            }

        overall = sum(score * weight for score, weight in available.values()) / available_weight

        return {
            "score": round(overall, 2),
            "components": component_scores,
            "rating": self._score_to_rating(overall, 100),
            "status": "complete" if len(available) == len(components) else "partial",
            "available_weight": round(available_weight, 2),
        }

    def _generate_recommendation(self, overall_score: dict) -> str:
        """Generate investment recommendation.

        Args:
            overall_score: Overall score dictionary

        Returns:
            Recommendation string
        """
        score = overall_score.get("score")

        if score is None:
            return "insufficient_data"

        if score >= 75:
            return "strong_buy"
        elif score >= 60:
            return "buy"
        elif score >= 45:
            return "hold"
        elif score >= 30:
            return "sell"
        else:
            return "strong_sell"

    def _score_to_rating(self, score: float, max_score: float) -> str:
        """Convert score to rating.

        Args:
            score: Actual score
            max_score: Maximum possible score

        Returns:
            Rating string
        """
        percentage = score / max_score if max_score > 0 else 0

        if percentage >= 0.8:
            return "excellent"
        elif percentage >= 0.6:
            return "good"
        elif percentage >= 0.4:
            return "fair"
        elif percentage >= 0.2:
            return "poor"
        else:
            return "very_poor"
