"""Decision making agent for investment recommendations."""

from datetime import datetime
from typing import Any

from app.agents.base import StatelessAgent
from app.orchestration.state import AgentState
from app.services.report_service import derive_recommendation
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

    async def process(self, state: AgentState) -> dict[str, Any]:
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
        logger.info(
            f"Data available - technical: {bool(technical)}, fundamental: {bool(fundamental)}, sentiment: {bool(sentiment)}, risk: {bool(risk)}"
        )

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
                # Conservative fallback: a dropped symbol means NO
                # recommendation at all — hold with zero confidence keeps
                # the report schema and symbol coverage intact.
                results[symbol] = {
                    "symbol": symbol,
                    "action": "hold",
                    "confidence": 0.0,
                    "score": 0.0,
                    "component_scores": {},
                    "position_size": {
                        "percentage_of_portfolio": 0,
                        "sizing_rationale": "Decision engine error; no position",
                    },
                    "price_targets": {},
                    "rationale": f"Decision engine error ({type(e).__name__}); defaulted to hold",
                    "warnings": [],
                }

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
        technical: dict,
        fundamental: dict,
        sentiment: dict,
        risk: dict,
    ) -> dict[str, Any]:
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
        # Component scores for display only.
        scores = {
            "technical": self._extract_technical_score(technical),
            "fundamental": self._extract_fundamental_score(fundamental),
            "sentiment": self._extract_sentiment_score(sentiment),
        }

        # Single action formula shared with the ReAct report path
        # (ReportService.derive_recommendation): fund 45% + tech 30% +
        # sentiment 15% + risk 10%, action bands and confidence included.
        # The old private weights (0.30/0.40/0.15 + multiplicative risk
        # penalty) are retired — two formulas meant two different
        # recommendations for the same data.
        recommendation = derive_recommendation(symbol, fundamental, technical, sentiment, risk)
        action = recommendation["action"]
        confidence = recommendation["confidence"]
        final_score = recommendation["composite_score"]

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

        # Canonical composite reasoning from the shared formula.
        rationale = recommendation["reasoning"]

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

    def _extract_technical_score(self, technical: dict) -> float:
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

    def _extract_fundamental_score(self, fundamental: dict) -> float:
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

    def _extract_sentiment_score(self, sentiment: dict) -> float:
        """Extract sentiment score (-100 to 100).

        Args:
            sentiment: Sentiment analysis results

        Returns:
            Sentiment score
        """
        if not sentiment:
            return 0.0

        return sentiment.get("score", 0.0)

    def _calculate_position_size(self, score: float, risk_rec: dict) -> dict[str, float]:
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

        # Cap by risk recommendation. Degraded risk payloads can carry an
        # explicit None — .get's default only fires when the key is absent.
        max_from_risk = risk_rec.get("max_position_size")
        if not isinstance(max_from_risk, int | float):
            max_from_risk = 10
        final_size = min(base_size, max_from_risk)

        return {
            "percentage_of_portfolio": final_size,
            "sizing_rationale": f"Based on conviction ({abs_score:.0f}/100) and risk limits",
        }

    def _calculate_price_targets(self, technical: dict, risk: dict) -> dict[str, Any]:
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

    def _generate_decision_warnings(self, action: str, risk: dict, confidence: float) -> list[str]:
        """Generate decision-specific warnings.

        Args:
            action: Recommended action
            risk: Risk assessment
            confidence: Confidence score

        Returns:
            List of warnings
        """
        warnings = []

        # Low confidence warning (confidence is 0-1 from derive_recommendation;
        # the old < 50 threshold compared against a 0-100 scale that no longer
        # exists, so the warning fired on every decision and meant nothing)
        if confidence < 0.5:
            warnings.append(
                "Low confidence in this recommendation. Consider waiting for clearer signals."
            )

        # High risk warning
        risk_level = risk.get("risk_level", "")
        if risk_level in ["high", "very_high"]:
            if "buy" in action:
                warnings.append("High risk stock - use strict stop-loss and limit position size.")

        # Strong action warning
        if "strong" in action:
            warnings.append("Strong conviction signal - ensure it aligns with your risk tolerance.")

        return warnings

    def _create_portfolio_summary(self, decisions: dict) -> dict[str, Any]:
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
            "buy_recommendations": actions.count("buy")
            + actions.count("strong_buy")
            + actions.count("moderate_buy"),
            "sell_recommendations": actions.count("sell")
            + actions.count("strong_sell")
            + actions.count("moderate_sell"),
            "hold_recommendations": actions.count("hold"),
            "avg_confidence": sum(d["confidence"] for d in decisions.values()) / len(decisions),
        }

    async def _llm_decision_synthesis(self, decisions: dict) -> dict[str, str]:
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
                    f"(confidence: {decision['confidence']:.0f%}, "
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
