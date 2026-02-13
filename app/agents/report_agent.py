"""Report generation agent for creating investment research reports."""

from datetime import datetime
from typing import Any, Dict, List

from app.agents.base import StatelessAgent
from app.orchestration.state import AgentState
from app.utils.logging import get_logger

logger = get_logger(__name__)


class ReportGenerationAgent(StatelessAgent):
    """Agent responsible for generating investment research reports.

    This agent:
    - Aggregates all analysis results
    - Uses LLM to generate natural language reports
    - Creates structured reports with sections
    - Formats output for different use cases
    - Includes charts and visualizations
    """

    async def process(self, state: AgentState) -> Dict[str, Any]:
        """Process report generation.

        Args:
            state: Current agent state

        Returns:
            Dictionary containing generated reports
        """
        query = state.get("query", "")
        symbols = state.get("symbols", [])

        logger.info(f"Generating report for query: {query}, symbols: {symbols}")

        # Collect all analysis data
        data = {
            "query": query,
            "symbols": symbols,
            "market_data": state.get("market_data", {}),
            "technical_analysis": state.get("technical_analysis", {}),
            "fundamental_analysis": state.get("fundamental_analysis", {}),
            "sentiment_analysis": state.get("sentiment_analysis", {}),
            "risk_assessment": state.get("risk_assessment", {}),
            "decisions": state.get("decision", {}).get("decisions", {}),
        }

        # Generate report sections
        sections = await self._generate_sections(data)

        # Generate executive summary
        executive_summary = await self._generate_executive_summary(data, sections)

        # Generate LLM report if available
        # TODO: Re-enable LLM report generation when timeout is fixed
        llm_report = None
        # if self.llm:
        #     try:
        #         llm_report = await self._generate_llm_report(data)
        #         logger.info("LLM report generated successfully")
        #     except Exception as e:
        #         logger.warning(f"LLM report generation failed, continuing without it: {e}")
        #         llm_report = None

        # Compile final report
        report = {
            "title": self._generate_title(query, symbols),
            "generated_at": datetime.now().isoformat(),
            "executive_summary": executive_summary,
            "sections": sections,
            "llm_report": llm_report,
            "metadata": {
                "symbols": symbols,
                "query": query,
                "data_points": self._count_data_points(data),
            },
        }

        logger.info("Report generation complete")

        return report

    async def _generate_sections(self, data: Dict) -> Dict[str, Any]:
        """Generate report sections.

        Args:
            data: Analysis data

        Returns:
            Dictionary of report sections
        """
        return {
            "overview": self._generate_overview(data),
            "technical_analysis": self._generate_technical_section(data),
            "fundamental_analysis": self._generate_fundamental_section(data),
            "sentiment_analysis": self._generate_sentiment_section(data),
            "risk_analysis": self._generate_risk_section(data),
            "recommendations": self._generate_recommendations_section(data),
        }

    def _generate_title(self, query: str, symbols: List[str]) -> str:
        """Generate report title.

        Args:
            query: User query
            symbols: Stock symbols

        Returns:
            Report title
        """
        if symbols:
            if len(symbols) == 1:
                return f"Investment Research Report: {symbols[0]}"
            else:
                return f"Investment Research Report: {', '.join(symbols[:3])}{'...' if len(symbols) > 3 else ''}"
        return "Investment Research Report"

    def _generate_overview(self, data: Dict) -> Dict[str, Any]:
        """Generate overview section.

        Args:
            data: Analysis data

        Returns:
            Overview section
        """
        symbols = data["symbols"]
        market_data = data["market_data"]

        overview = {
            "symbols_analyzed": symbols,
            "analysis_date": datetime.now().strftime("%Y-%m-%d"),
            "market_summary": {},
        }

        for symbol in symbols:
            mkt = market_data.get(symbol, {})
            overview["market_summary"][symbol] = {
                "company_name": mkt.get("company_name"),
                "current_price": mkt.get("current_price"),
                "change": mkt.get("change"),
                "change_percent": mkt.get("change_percent"),
                "volume": mkt.get("volume"),
                "market_cap": mkt.get("market_cap"),
                "sector": mkt.get("sector"),
            }

        return overview

    def _generate_technical_section(self, data: Dict) -> Dict[str, Any]:
        """Generate technical analysis section.

        Args:
            data: Analysis data

        Returns:
            Technical analysis section
        """
        technical = data["technical_analysis"]
        summary = {
            "by_symbol": {},
            "overall_outlook": "neutral",
        }

        bullish_count = 0
        bearish_count = 0

        for symbol, analysis in technical.items():
            sentiment = analysis.get("sentiment", {})
            score = sentiment.get("score", 0)
            signals = analysis.get("signals", {})

            summary["by_symbol"][symbol] = {
                "trend": signals.get("trend", "neutral"),
                "rsi": signals.get("rsi", "neutral"),
                "macd": signals.get("macd", "neutral"),
                "support": analysis.get("support", {}),
                "resistance": analysis.get("resistance", {}),
                "sentiment_score": score,
            }

            if score > 20:
                bullish_count += 1
            elif score < -20:
                bearish_count += 1

        if bullish_count > bearish_count:
            summary["overall_outlook"] = "bullish"
        elif bearish_count > bullish_count:
            summary["overall_outlook"] = "bearish"

        return summary

    def _generate_fundamental_section(self, data: Dict) -> Dict[str, Any]:
        """Generate fundamental analysis section.

        Args:
            data: Analysis data

        Returns:
            Fundamental analysis section
        """
        fundamental = data["fundamental_analysis"]
        summary = {
            "by_symbol": {},
            "overall_rating": "hold",
        }

        total_score = 0

        for symbol, analysis in fundamental.items():
            overall = analysis.get("overall_score", {})
            score = overall.get("score", 50)
            rating = overall.get("rating", "fair")

            summary["by_symbol"][symbol] = {
                "overall_score": score,
                "rating": rating,
                "recommendation": analysis.get("recommendation", "hold"),
                "profitability": analysis.get("profitability", {}).get("rating", "N/A"),
                "valuation": analysis.get("valuation", {}).get("rating", "N/A"),
                "financial_health": analysis.get("financial_health", {}).get("rating", "N/A"),
            }

            total_score += score

        if fundamental:
            avg_score = total_score / len(fundamental)
            if avg_score >= 65:
                summary["overall_rating"] = "buy"
            elif avg_score >= 35:
                summary["overall_rating"] = "hold"
            else:
                summary["overall_rating"] = "sell"

        return summary

    def _generate_sentiment_section(self, data: Dict) -> Dict[str, Any]:
        """Generate sentiment analysis section.

        Args:
            data: Analysis data

        Returns:
            Sentiment analysis section
        """
        sentiment = data["sentiment_analysis"]
        sentiment_by_symbol = sentiment.get("sentiment_by_symbol", {})

        summary = {
            "by_symbol": {},
            "overall": sentiment.get("overall_sentiment", {}),
        }

        for symbol, analysis in sentiment_by_symbol.items():
            summary["by_symbol"][symbol] = {
                "sentiment": analysis.get("sentiment", "neutral"),
                "score": analysis.get("score", 0),
                "trend": analysis.get("trend", "stable"),
                "article_count": analysis.get("article_count", 0),
            }

        return summary

    def _generate_risk_section(self, data: Dict) -> Dict[str, Any]:
        """Generate risk analysis section.

        Args:
            data: Analysis data

        Returns:
            Risk analysis section
        """
        risk = data["risk_assessment"]
        risk_by_symbol = risk.get("risk_by_symbol", {})

        summary = {
            "by_symbol": {},
            "portfolio_risk": risk.get("portfolio_risk", {}),
            "overall_risk": risk.get("overall_risk_level", "medium"),
        }

        for symbol, analysis in risk_by_symbol.items():
            metrics = analysis.get("metrics", {})
            position_rec = analysis.get("position_recommendation", {})

            summary["by_symbol"][symbol] = {
                "risk_level": analysis.get("risk_level", "medium"),
                "risk_score": analysis.get("risk_score", 50),
                "volatility": metrics.get("volatility_annualized"),
                "max_position_size": position_rec.get("max_position_size"),
                "warnings": analysis.get("warnings", []),
            }

        return summary

    def _generate_recommendations_section(self, data: Dict) -> Dict[str, Any]:
        """Generate recommendations section.

        Args:
            data: Analysis data

        Returns:
            Recommendations section
        """
        decisions = data["decisions"]

        summary = {
            "by_symbol": {},
            "portfolio_actions": [],
            "top_pick": None,
            "avoid": [],
        }

        best_score = -float("inf")
        worst_score = float("inf")

        for symbol, decision in decisions.items():
            action = decision["action"]
            score = decision.get("score", 0)

            summary["by_symbol"][symbol] = {
                "action": action,
                "confidence": decision.get("confidence"),
                "position_size": decision.get("position_size", {}).get("percentage_of_portfolio"),
                "entry": decision.get("price_targets", {}).get("entry_zone"),
                "stop_loss": decision.get("price_targets", {}).get("stop_loss"),
                "take_profit": decision.get("price_targets", {}).get("take_profit"),
                "rationale": decision.get("rationale"),
            }

            # Categorize actions
            if "buy" in action:
                summary["portfolio_actions"].append({"symbol": symbol, "action": action})
            elif "sell" in action:
                summary["avoid"].append(symbol)

            # Track best/worst
            if score > best_score:
                best_score = score
                summary["top_pick"] = symbol
            if score < worst_score:
                worst_score = score

        return summary

    async def _generate_executive_summary(
        self, data: Dict, sections: Dict
    ) -> str:
        """Generate executive summary.

        Args:
            data: Analysis data
            sections: Report sections

        Returns:
            Executive summary string
        """
        symbols = data["symbols"]
        decisions = data.get("decisions", {})

        parts = []

        # Introduction
        if len(symbols) == 1:
            parts.append(f"This report analyzes {symbols[0]} across technical, fundamental, sentiment, and risk dimensions.")
        else:
            parts.append(f"This report analyzes {len(symbols)} stocks across technical, fundamental, sentiment, and risk dimensions.")

        # Overall recommendations
        recs = sections.get("recommendations", {})
        top_pick = recs.get("top_pick")
        if top_pick:
            top_decision = decisions.get(top_pick, {})
            parts.append(f"Our top pick is {top_pick} ({top_decision.get('action', 'hold')}) with {top_decision.get('confidence', 0):.0f}% confidence.")

        # Risk overview
        risk = sections.get("risk_analysis", {})
        overall_risk = risk.get("overall_risk", "medium")
        parts.append(f"Overall risk level for the analyzed stocks is {overall_risk}.")

        # Technical outlook
        technical = sections.get("technical_analysis", {})
        tech_outlook = technical.get("overall_outlook", "neutral")
        parts.append(f"Technical indicators show a {tech_outlook} outlook.")

        return " ".join(parts)

    async def _generate_llm_report(self, data: Dict) -> str:
        """Generate LLM-powered report.

        Args:
            data: Analysis data

        Returns:
            LLM-generated report text
        """
        try:
            symbols = data["symbols"]
            decisions = data["decisions"]

            # Prepare decision summary
            decision_summary = []
            for symbol, decision in decisions.items():
                decision_summary.append(
                    f"- {symbol}: {decision['action']} "
                    f"(confidence: {decision['confidence']:.0f}%)"
                )

            prompt = f"""Generate a concise investment research report for the following analysis:

Symbols: {', '.join(symbols)}
Query: {data.get('query', 'General analysis')}

Key Decisions:
{chr(10).join(decision_summary)}

Include these sections:
1. Executive Summary (2-3 sentences)
2. Key Findings
3. Investment Recommendations
4. Risk Considerations
5. Conclusion

Keep the report professional, concise, and actionable."""

            response = await self.invoke_llm(prompt, temperature=0.3)

            return response

        except Exception as e:
            logger.error(f"LLM report generation failed: {e}")
            return ""

    def _count_data_points(self, data: Dict) -> int:
        """Count total data points analyzed.

        Args:
            data: Analysis data

        Returns:
            Number of data points
        """
        count = 0
        count += len(data.get("market_data", {}))
        count += len(data.get("technical_analysis", {}))
        count += len(data.get("fundamental_analysis", {}))
        count += len(data.get("decisions", {}))
        count += sum(len(v) for v in data.get("sentiment_analysis", {}).get("sentiment_by_symbol", {}).values())
        return count
