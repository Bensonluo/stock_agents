"""Decision making agent for investment recommendations."""

from datetime import datetime
from typing import Any

from app.agents.base import StatelessAgent
from app.analysis.sizing import RISK_BUDGET_PCT, STOP_MULTIPLE, atr_position_size
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
            market_regime = risk_assessment.get("market_regime")
        else:
            risk = {}
            market_regime = None

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
                    market_regime=market_regime,
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
            llm_summary = await self._llm_decision_synthesis(results, market_regime)

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
        *,
        market_regime: dict | None = None,
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
        # sentiment 15% + risk 10% renormalized over the dimensions that
        # actually have data, action bands and confidence included.
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
            technical,
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
            "warnings": self._generate_decision_warnings(action, risk, confidence)
            + _regime_warnings(action, market_regime),
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

    def _calculate_position_size(
        self, score: float, risk_rec: dict, technical: dict | None = None
    ) -> dict[str, float]:
        """Calculate recommended position size.

        Volatility-first: when ATR% is available, size = risk budget /
        stop distance (2xATR), so every position risks the same portfolio
        slice regardless of how choppy the stock is. Without ATR (spot-only
        symbols, degraded runs) the conviction bands below apply.

        Args:
            score: Decision score
            risk_rec: Risk recommendation
            technical: Per-symbol technical analysis (indicators.atr_pct)

        Returns:
            Position size details
        """
        atr_pct = (technical or {}).get("indicators", {}).get("atr_pct")
        vol_size = atr_position_size(atr_pct)

        if vol_size is not None:
            base_size = vol_size
            rationale = (
                f"Volatility-sized: {RISK_BUDGET_PCT:g}% portfolio risk over a "
                f"{STOP_MULTIPLE:g}xATR stop (ATR {atr_pct:.2f}%/day)"
            )
        else:
            # Base position size from conviction. Zero-evidence runs carry a
            # None composite — no conviction to size on, so the floor applies.
            abs_score = abs(score) if isinstance(score, int | float) else 0
            if abs_score >= 50:
                base_size = 20  # 20% of portfolio max
            elif abs_score >= 25:
                base_size = 15
            elif abs_score >= 10:
                base_size = 10
            else:
                base_size = 5
            rationale = f"Based on conviction ({abs_score:.0f}/100) and risk limits"

        # Cap by risk recommendation. Degraded risk payloads can carry an
        # explicit None — .get's default only fires when the key is absent.
        max_from_risk = risk_rec.get("max_position_size")
        if not isinstance(max_from_risk, int | float):
            max_from_risk = 10
        final_size = min(base_size, max_from_risk)

        return {
            "percentage_of_portfolio": final_size,
            "sizing_rationale": rationale,
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

    async def _llm_decision_synthesis(
        self, decisions: dict, market_regime: dict | None = None
    ) -> dict[str, str]:
        """Use LLM to synthesize decisions.

        Args:
            decisions: Decisions by symbol
            market_regime: Benchmark regime block (iteration 76) — context
                for the narrative, never an input to any score

        Returns:
            LLM synthesis
        """
        try:
            # Prepare summary. Zero-evidence runs carry score=None — render
            # it as "n/a" instead of letting {None:.0f} raise and swallow
            # the whole synthesis into the except branch.
            summary_parts = []
            for symbol, decision in decisions.items():
                score = decision["score"]
                score_str = f"{score:.0f}" if isinstance(score, int | float) else "n/a"
                summary_parts.append(
                    f"{symbol}: {decision['action']} "
                    f"(confidence: {decision['confidence']:.0%}, "
                    f"score: {score_str})"
                )

            context = _market_context_line(market_regime)
            context_block = f"{context}\n\n" if context else ""

            prompt = f"""Synthesize these investment decisions into a brief portfolio summary:

{chr(10).join(summary_parts)}

{context_block}Provide:
1. Overall portfolio strategy (2-3 sentences)
2. Top pick and reasoning
3. Main risks to watch

Keep it concise and actionable. Frame the strategy in the market context above when provided."""

            response = await self.invoke_llm(prompt)

            return {
                "synthesis": response[:500],
                "top_pick": max(
                    decisions.items(),
                    key=lambda item: (
                        item[1]["score"]
                        if isinstance(item[1]["score"], int | float)
                        else -float("inf")
                    ),
                )[0],
            }

        except Exception as e:
            logger.error(f"LLM decision synthesis failed: {e}")
            return {}


_TREND_WORDS = {"bull": "an uptrend", "bear": "a downtrend", "neutral": "a range"}
_VOL_WORDS = {"elevated": "elevated", "calm": "calm", "normal": "normal"}


def _market_context_line(regime: dict | None) -> str | None:
    """One-line market context for the synthesis prompt; None when unknown.

    Reads the iteration-76 regime block (annotation-only). Narrative
    context for the LLM — deliberately NOT an input to any score,
    weight, or position size.
    """
    if not isinstance(regime, dict) or regime.get("status") != "ok":
        return None
    parts: list[str] = []
    trend = regime.get("trend")
    if trend in _TREND_WORDS:
        vs_sma = regime.get("price_vs_sma200")
        detail = (
            f" ({vs_sma:+.1%} vs its 200-day average)" if isinstance(vs_sma, int | float) else ""
        )
        parts.append(f"the benchmark is in {_TREND_WORDS[trend]}{detail}")
    vol = regime.get("volatility_regime")
    if vol in _VOL_WORDS:
        ratio = regime.get("vol_ratio_20d_vs_full")
        detail = (
            f" (recent volatility {ratio:.1f}x the full-window level)"
            if isinstance(ratio, int | float)
            else ""
        )
        parts.append(f"volatility is {vol}{detail}")
    drawdown = regime.get("drawdown_from_52w_high")
    if isinstance(drawdown, int | float):
        parts.append(f"{abs(drawdown):.1%} below its 52-week high")
    if not parts:
        return None
    return (
        f"Market context: benchmark series over {regime.get('bars', '?')} bars — "
        + "; ".join(parts)
        + "."
    )


def _regime_warnings(action: str, regime: dict | None) -> list[str]:
    """Buy-side risk warnings from the market regime (iteration 76 block).

    Pure annotation, in the liquidity / sector_relative tradition: the
    regime can only APPEND warning strings — never an input to the
    action, score, confidence, or position size (all decided before
    this runs). Sells/holds get nothing: the regime's edge case is a
    recommendation to add risk into a hostile market.
    """
    if not isinstance(regime, dict) or regime.get("status") != "ok" or "buy" not in action:
        return []

    warnings: list[str] = []
    if regime.get("trend") == "bear":
        vs_sma = regime.get("price_vs_sma200")
        where = (
            f" ({vs_sma:+.1%} vs its 200-day average)" if isinstance(vs_sma, int | float) else ""
        )
        warnings.append(
            "Counter-trend entry: the benchmark is in a bear regime"
            f"{where} — counter-trend buys historically carry lower hit rates."
        )
    if regime.get("volatility_regime") == "elevated":
        ratio = regime.get("vol_ratio_20d_vs_full")
        scale = f" ({ratio:.1f}x its full-window level)" if isinstance(ratio, int | float) else ""
        warnings.append(
            f"Market volatility is elevated{scale} — expect wider swings and size accordingly."
        )
    drawdown = regime.get("drawdown_from_52w_high")
    if isinstance(drawdown, int | float) and drawdown <= -0.20:
        warnings.append(
            f"Benchmark sits {abs(drawdown):.1%} below its 52-week high — "
            "falling-knife risk; prefer scaling in over a single entry."
        )
    return warnings
