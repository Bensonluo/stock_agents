"""Report generation agent for creating investment research reports."""

import asyncio
from datetime import datetime
from typing import Any

from app.agents.base import StatelessAgent
from app.config import settings
from app.orchestration.state import AgentState
from app.services.report_service import ReportService
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

    async def process(self, state: AgentState) -> dict[str, Any]:
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
            "financial_data": state.get("financial_data", {}),
            "technical_analysis": state.get("technical_analysis", {}),
            "fundamental_analysis": state.get("fundamental_analysis", {}),
            "sentiment_analysis": state.get("sentiment_analysis", {}),
            "risk_assessment": state.get("risk_assessment", {}),
            "decisions": state.get("decision", {}).get("decisions", {}),
            "research_synthesis": state.get("research_synthesis", {}),
        }

        # Generate report sections (deterministic, synchronous delegate)
        sections = self._generate_sections(data)

        # Generate executive summary
        executive_summary = await self._generate_executive_summary(data, sections)

        # Optional LLM narrative overlay. Bounded by REPORT_LLM_TIMEOUT and
        # degrades to None on failure or timeout, so the deterministic report
        # always ships.
        llm_report = None
        if self.llm and settings.report_llm_enabled:
            try:
                llm_report = (
                    await asyncio.wait_for(
                        self._generate_llm_report(data), timeout=settings.report_llm_timeout
                    )
                    or None
                )
                if llm_report:
                    logger.info("LLM report generated successfully")
            except TimeoutError:
                logger.warning(
                    f"LLM report timed out after {settings.report_llm_timeout}s, "
                    "continuing without it"
                )
                llm_report = None
            except Exception as e:
                logger.warning(f"LLM report generation failed, continuing without it: {e}")
                llm_report = None

        # Compile final report
        report = {
            "title": ReportService.build_title(query, symbols),
            "generated_at": datetime.now().isoformat(),
            "executive_summary": executive_summary,
            "sections": sections,
            "llm_report": llm_report,
            # The decision agent's LLM synthesis (regime-aware since
            # iteration 77) used to die in state — nothing read it. It is
            # narrative only; every number below stays deterministic.
            "decision_synthesis": state.get("decision", {}).get("llm_summary") or None,
            "metadata": {
                "symbols": symbols,
                "query": query,
                "data_points": self._count_data_points(data),
            },
        }

        logger.info("Report generation complete")

        return report

    def _generate_sections(self, data: dict) -> dict[str, Any]:
        """Delegate to the shared ReportService."""
        return ReportService.build_sections(data)

    def _generate_technical_section(self, data: dict) -> dict[str, Any]:
        """Delegate to the shared ReportService."""
        return ReportService.build_sections(data)["technical_analysis"]

    async def _generate_executive_summary(self, data: dict, sections: dict) -> str:
        """Deterministic, i18n-aware summary from the shared ReportService."""
        return ReportService.executive_summary(data, sections)

    async def _generate_llm_report(self, data: dict) -> str:
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

    def _count_data_points(self, data: dict) -> int:
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
        count += sum(
            len(v)
            for v in data.get("sentiment_analysis", {}).get("sentiment_by_symbol", {}).values()
        )
        return count
