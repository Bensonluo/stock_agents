"""Decision making agent for investment recommendations."""

from datetime import datetime
from typing import Any, Dict, List

from app.agents.base import StatelessAgent
from app.orchestration.state import AgentState
from app.utils.logging import get_logger

logger = get_logger(__name__)


class DecisionMakingAgent(StatelessAgent):
    """Agent responsible for making investment decisions.

    This agent:
    - Aggregates signals from all analysis agents
    - Weights different factors (technical, fundamental, sentiment, risk)
    - Generates investment decisions (buy/sell/hold)
    - Calculates position sizing
    - Provides decision rationale
    - Suggests entry/exit points
    """

    async def process(self, state: AgentState) -> Dict[str, Any]:
        """Process investment decision making.

        Args:
            state: Current agent state

        Returns:
            Dictionary containing investment decisions
        """
        symbols = state.get("symbols", [])
        technical = state.get("technical_analysis", {})
        fundamental = state.get("fundamental_analysis", {})

        # Get sentiment data - it's structured with sentiment_by_symbol inside
        sentiment_analysis = state.get("sentiment_analysis", {})
        if sentiment_analysis and isinstance(sentiment_analysis, dict):
            sentiment = sentiment_analysis.get("sentiment_by_symbol", sentiment_analysis)
        else:
            sentiment = {}

        # Get risk data - it's structured with risk_by_symbol inside
        risk_assessment = state.get("risk_assessment", {})
        if risk_assessment and isinstance(risk_assessment, dict):
            risk = risk_assessment.get("risk_by_symbol", risk_assessment)
        else:
            risk = {}

        if not symbols:
            logger.warning("No symbols for decision making")
            return {}

        logger.info(f"Making investment decisions for {len(symbols)} symbols")
        logger.info(f"Data available - technical: {bool(technical)}, fundamental: {bool(fundamental)}, sentiment: {bool(sentiment)}, risk: {bool(risk)}")

        results = {}

        for symbol in symbols:
            try:
                decision = await self._make_decision(
                    symbol,
                    technical.get(symbol, {}) if isinstance(technical, dict) else technical,
                    fundamental.get(symbol, {}) if isinstance(fundamental, dict) else fundamental,
                    sentiment.get(symbol, {}) if isinstance(sentiment, dict) else sentiment,
                    risk.get(symbol, {}) if isinstance(risk, dict) else risk,
                )
                if decision:
                    results[symbol] = decision
            except Exception as e:
                logger.error(f"Error making decision for {symbol}: {e}")
                import traceback
                traceback.print_exc()

        # Use LLM for final decision synthesis if available
        llm_summary = None
        if self.llm and results:
            llm_summary = await self._llm_decision_synthesis(results)

        return {
            "decisions": results,
            "llm_summary": llm_summary,
            "portfolio_summary": self._create_portfolio_summary(results),
            "timestamp": datetime.now().isoformat(),
        }

    async def _make_decision(
        self,
        symbol: str,
        technical: Dict,
        fundamental: Dict,
        sentiment: Dict,
        risk: Dict,
    ) -> Dict[str, Any]:
        """Make investment decision for a single symbol.

        Args:
            symbol: Stock symbol
            technical: Technical analysis results
            fundamental: Fundamental analysis results
            sentiment: Sentiment analysis results
            risk: Risk assessment results

        Returns:
            Decision dictionary
        """
        # Collect scores
        scores = {
            "technical": self._extract_technical_score(technical),
            "fundamental": self._extract_fundamental_score(fundamental),
            "sentiment": self._extract_sentiment_score(sentiment),
        }

        # Apply weights
        weights = {
            "technical": 0.30,
            "fundamental": 0.40,
            "sentiment": 0.15,
            "risk_adjustment": 0.15,
        }

        # Calculate weighted score
        base_score = (
            scores["technical"] * weights["technical"] +
            scores["fundamental"] * weights["fundamental"] +
            scores["sentiment"] * weights["sentiment"]
        )

        # Apply risk adjustment
        risk_penalty = self._calculate_risk_penalty(risk)
        final_score = base_score * (1 - risk_penalty)

        # Determine action
        action = self._score_to_action(final_score)

        # Calculate confidence
        confidence = self._calculate_confidence(scores, final_score)

        # Get position size
        position_size = self._calculate_position_size(
            final_score,
            risk.get("position_recommendation", {}),
        )

        # Get entry/exit points
        price_targets = self._calculate_price_targets(
            technical,
            risk,
        )

        # Generate rationale
        rationale = self._generate_rationale(scores, action, risk)

        return {
            "symbol": symbol,
            "action": action,
            "confidence": confidence,
            "score": final_score,
            "component_scores": scores,
            "position_size": position_size,
            "price_targets": price_targets,
            "rationale": rationale,
            "warnings": self._generate_decision_warnings(action, risk, confidence),
        }

    def _extract_technical_score(self, technical: Dict) -> float:
        """Extract technical analysis score (-100 to 100).

        Args:
            technical: Technical analysis results

        Returns:
            Technical score
        """
        if not technical:
            return 0.0

        sentiment = technical.get("sentiment", {})
        return sentiment.get("score", 0.0)

    def _extract_fundamental_score(self, fundamental: Dict) -> float:
        """Extract fundamental analysis score (0 to 100).

        Args:
            fundamental: Fundamental analysis results

        Returns:
            Fundamental score converted to -100 to 100 scale
        """
        if not fundamental:
            return 0.0

        overall = fundamental.get("overall_score", {})
        score = overall.get("score", 50)

        # Convert 0-100 to -50 to 50 scale
        return (score - 50) * 2

    def _extract_sentiment_score(self, sentiment: Dict) -> float:
        """Extract sentiment score (-100 to 100).

        Args:
            sentiment: Sentiment analysis results

        Returns:
            Sentiment score
        """
        if not sentiment:
            return 0.0

        return sentiment.get("score", 0.0)

    def _calculate_risk_penalty(self, risk: Dict) -> float:
        """Calculate risk penalty (0 to 1, where 1 = no adjustment).

        Args:
            risk: Risk assessment results

        Returns:
            Risk penalty multiplier (lower = more penalty)
        """
        if not risk:
            return 0.0

        risk_level = risk.get("risk_level", "medium")

        penalties = {
            "very_low": 0.0,
            "low": 0.0,
            "medium": 0.0,
            "high": 0.1,
            "very_high": 0.25,
        }

        return penalties.get(risk_level, 0.15)

    def _score_to_action(self, score: float) -> str:
        """Convert score to action.

        Args:
            score: Final decision score

        Returns:
            Action string
        """
        if score >= 50:
            return "strong_buy"
        elif score >= 25:
            return "buy"
        elif score >= 10:
            return "moderate_buy"
        elif score <= -50:
            return "strong_sell"
        elif score <= -25:
            return "sell"
        elif score <= -10:
            return "moderate_sell"
        else:
            return "hold"

    def _calculate_confidence(self, scores: Dict, final_score: float) -> float:
        """Calculate confidence in decision.

        Args:
            scores: Component scores
            final_score: Final decision score

        Returns:
            Confidence score (0-100)
        """
        # Confidence based on agreement of signals
        tech_sign = 1 if scores["technical"] > 0 else -1 if scores["technical"] < 0 else 0
        fund_sign = 1 if scores["fundamental"] > 0 else -1 if scores["fundamental"] < 0 else 0
        sent_sign = 1 if scores["sentiment"] > 0 else -1 if scores["sentiment"] < 0 else 0

        # Count agreement
        agreement = 0
        if tech_sign == fund_sign:
            agreement += 1
        if fund_sign == sent_sign:
            agreement += 1
        if tech_sign == sent_sign:
            agreement += 1

        # Base confidence on agreement and magnitude
        base_confidence = (agreement / 3) * 70

        # Add magnitude bonus
        magnitude_bonus = min(30, abs(final_score) / 100 * 30)

        return min(100, base_confidence + magnitude_bonus)

    def _calculate_position_size(
        self, score: float, risk_rec: Dict
    ) -> Dict[str, float]:
        """Calculate recommended position size.

        Args:
            score: Decision score
            risk_rec: Risk recommendation

        Returns:
            Position size details
        """
        # Base position size from conviction
        abs_score = abs(score)
        if abs_score >= 50:
            base_size = 20  # 20% of portfolio max
        elif abs_score >= 25:
            base_size = 15
        elif abs_score >= 10:
            base_size = 10
        else:
            base_size = 5

        # Cap by risk recommendation
        max_from_risk = risk_rec.get("max_position_size", 10)
        final_size = min(base_size, max_from_risk)

        return {
            "percentage_of_portfolio": final_size,
            "sizing_rationale": f"Based on conviction ({abs_score:.0f}/100) and risk limits",
        }

    def _calculate_price_targets(
        self, technical: Dict, risk: Dict
    ) -> Dict[str, Any]:
        """Calculate entry, stop loss, and take profit targets.

        Args:
            technical: Technical analysis
            risk: Risk assessment

        Returns:
            Price targets
        """
        targets = {}

        # Get current price and levels
        current_price = technical.get("current_price")
        support = technical.get("support", {})
        resistance = technical.get("resistance", {})

        if current_price:
            targets["current"] = current_price

            # Entry zones
            r1 = resistance.get("r1")
            s1 = support.get("s1")

            if r1 and s1:
                targets["entry_zone"] = {
                    "lower": s1,
                    "upper": r1,
                    "ideal": current_price,
                }

            # Stop loss
            sl_pct = risk.get("position_recommendation", {}).get("stop_loss_percentage")
            if sl_pct:
                targets["stop_loss"] = current_price * (1 - sl_pct / 100)
            elif s1:
                targets["stop_loss"] = s1 * 0.98  # 2% below support

            # Take profit
            if r1:
                targets["take_profit"] = r1 * 0.98  # Just below resistance
            elif current_price:
                targets["take_profit"] = current_price * 1.1  # 10% gain

        return targets

    def _generate_rationale(self, scores: Dict, action: str, risk: Dict) -> str:
        """Generate decision rationale.

        Args:
            scores: Component scores
            action: Recommended action
            risk: Risk assessment

        Returns:
            Rationale string
        """
        parts = []

        # Technical
        tech = scores["technical"]
        if tech > 30:
            parts.append("Technical indicators show strong bullish momentum")
        elif tech > 10:
            parts.append("Technical analysis is moderately positive")
        elif tech < -30:
            parts.append("Technical indicators show bearish momentum")
        elif tech < -10:
            parts.append("Technical analysis is moderately negative")
        else:
            parts.append("Technical indicators are neutral")

        # Fundamental
        fund = scores["fundamental"]
        if fund > 30:
            parts.append("Fundamentals are strong with good valuation")
        elif fund > 10:
            parts.append("Fundamentals are reasonably attractive")
        elif fund < -30:
            parts.append("Fundamentals appear weak or overvalued")
        elif fund < -10:
            parts.append("Fundamentals show some concerns")
        else:
            parts.append("Fundamentals are fair")

        # Sentiment
        sent = scores["sentiment"]
        if sent > 20:
            parts.append("Market sentiment is positive")
        elif sent < -20:
            parts.append("Market sentiment is negative")
        else:
            parts.append("Market sentiment is neutral")

        # Risk
        risk_level = risk.get("risk_level", "medium")
        if risk_level == "high":
            parts.append("Elevated risk suggests smaller position size")
        elif risk_level == "very_high":
            parts.append("High risk - consider reducing exposure")

        return ". ".join(parts) + "."

    def _generate_decision_warnings(
        self, action: str, risk: Dict, confidence: float
    ) -> List[str]:
        """Generate decision-specific warnings.

        Args:
            action: Recommended action
            risk: Risk assessment
            confidence: Confidence score

        Returns:
            List of warnings
        """
        warnings = []

        # Low confidence warning
        if confidence < 50:
            warnings.append("Low confidence in this recommendation. Consider waiting for clearer signals.")

        # High risk warning
        risk_level = risk.get("risk_level", "")
        if risk_level in ["high", "very_high"]:
            if "buy" in action:
                warnings.append("High risk stock - use strict stop-loss and limit position size.")

        # Strong action warning
        if "strong" in action:
            warnings.append("Strong conviction signal - ensure it aligns with your risk tolerance.")

        return warnings

    def _create_portfolio_summary(self, decisions: Dict) -> Dict[str, Any]:
        """Create portfolio-level summary.

        Args:
            decisions: Decisions by symbol

        Returns:
            Portfolio summary
        """
        if not decisions:
            return {}

        actions = [d["action"] for d in decisions.values()]

        return {
            "total_symbols": len(decisions),
            "buy_recommendations": actions.count("buy") + actions.count("strong_buy") + actions.count("moderate_buy"),
            "sell_recommendations": actions.count("sell") + actions.count("strong_sell") + actions.count("moderate_sell"),
            "hold_recommendations": actions.count("hold"),
            "avg_confidence": sum(d["confidence"] for d in decisions.values()) / len(decisions),
        }

    async def _llm_decision_synthesis(self, decisions: Dict) -> Dict[str, str]:
        """Use LLM to synthesize decisions.

        Args:
            decisions: Decisions by symbol

        Returns:
            LLM synthesis
        """
        try:
            # Prepare summary
            summary_parts = []
            for symbol, decision in decisions.items():
                summary_parts.append(
                    f"{symbol}: {decision['action']} "
                    f"(confidence: {decision['confidence']:.0f}%, "
                    f"score: {decision['score']:.0f})"
                )

            prompt = f"""Synthesize these investment decisions into a brief portfolio summary:

{chr(10).join(summary_parts)}

Provide:
1. Overall portfolio strategy (2-3 sentences)
2. Top pick and reasoning
3. Main risks to watch

Keep it concise and actionable."""

            response = await self.invoke_llm(prompt)

            return {
                "synthesis": response[:500],
                "top_pick": max(decisions.items(), key=lambda x: x[1]["score"])[0],
            }

        except Exception as e:
            logger.error(f"LLM decision synthesis failed: {e}")
            return {}
