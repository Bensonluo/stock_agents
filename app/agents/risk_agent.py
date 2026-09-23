"""Risk assessment agent for evaluating investment risks.

Per-symbol metrics are computed by the shared engine path
(``app/tools/risk/assessment.assess_symbol`` over ``app/analysis/risk``) —
this agent owns only pipeline orchestration and the portfolio-level summary,
so the LangGraph pipeline and the ReAct tools report identical numbers.
"""

from datetime import datetime
from typing import Any

from app.agents.base import StatelessAgent
from app.orchestration.state import AgentState
from app.tools.risk.assessment import (
    _calculate_beta,
    _calculate_score,
    _minimal_risk,
    _position_size,
    _score_to_level,
    assess_symbol,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)


class RiskAssessmentAgent(StatelessAgent):
    """Agent responsible for risk assessment of stock investments.

    This agent:
    - Calculates market risk metrics (Beta, VaR, CVaR, volatility)
    - Assesses portfolio risk
    - Evaluates downside risk
    - Provides risk warnings
    - Suggests position sizing based on risk
    """

    async def process(self, state: AgentState) -> dict[str, Any]:
        """Process risk assessment.

        Args:
            state: Current agent state

        Returns:
            Dictionary containing risk assessment results
        """
        market_data = state.get("market_data", {})
        symbols = state.get("symbols", [])

        if not market_data:
            logger.warning("No market data available for risk assessment")
            return {}

        logger.info(f"Assessing risk for {len(symbols)} symbols")

        results = {}

        for symbol, data in market_data.items():
            try:
                risk = await self._assess_risk(symbol, data)
                if risk:
                    results[symbol] = risk
            except Exception as e:
                logger.error(f"Error assessing risk for {symbol}: {e}")

        # Calculate portfolio-level risk if multiple symbols
        portfolio_risk = None
        if len(results) > 1:
            portfolio_risk = self._assess_portfolio_risk(results)

        return {
            "risk_by_symbol": results,
            "portfolio_risk": portfolio_risk,
            "overall_risk_level": self._calculate_overall_risk(results),
            "timestamp": datetime.now().isoformat(),
        }

    async def _assess_risk(self, symbol: str, data: dict) -> dict[str, Any]:
        """Assess risk for a single symbol via the shared engine path."""
        return assess_symbol(symbol, data)

    def _estimate_beta(self, returns, benchmark_returns=None) -> float | None:
        """Beta from paired returns; None when evidence is insufficient."""
        return _calculate_beta(returns, benchmark_returns)

    def _calculate_risk_score(self, metrics: dict) -> float | None:
        """Risk score (0-100, higher = riskier); None when core metrics miss."""
        return _calculate_score(
            metrics.get("volatility"),
            metrics.get("max_drawdown"),
            metrics.get("var_95"),
            metrics.get("beta"),
        )

    def _risk_score_to_level(self, score: float | None) -> str:
        return _score_to_level(score)

    def _calculate_position_size(self, risk_score: float | None) -> float | None:
        return _position_size(risk_score)

    def _minimal_risk_assessment(self, data: dict) -> dict[str, Any]:
        """Minimal assessment for symbols without usable history."""
        return _minimal_risk(data, data.get("symbol", ""))

    def _assess_portfolio_risk(self, results: dict[str, dict]) -> dict[str, Any]:
        """Assess portfolio-level risk.

        Args:
            results: Risk assessment by symbol

        Returns:
            Portfolio risk summary
        """
        # Calculate average risk metrics
        risk_scores = [
            score
            for result in results.values()
            if isinstance((score := result.get("risk_score")), int | float)
        ]
        avg_risk_score = sum(risk_scores) / len(risk_scores) if risk_scores else None

        # Count by risk level
        risk_levels = [r.get("risk_level", "medium") for r in results.values()]

        return {
            "avg_risk_score": avg_risk_score,
            "portfolio_risk_level": self._risk_score_to_level(avg_risk_score),
            "risk_distribution": {
                "very_high": risk_levels.count("very_high"),
                "high": risk_levels.count("high"),
                "medium": risk_levels.count("medium"),
                "low": risk_levels.count("low"),
                "very_low": risk_levels.count("very_low"),
                "insufficient_data": risk_levels.count("insufficient_data"),
            },
            "diversification_score": self._calculate_diversification_score(results),
        }

    def _calculate_diversification_score(self, results: dict[str, dict]) -> float:
        """Calculate diversification score.

        Args:
            results: Risk assessment by symbol

        Returns:
            Diversification score (0-100)
        """
        # Simple metric based on number of holdings
        num_holdings = len(results)

        if num_holdings >= 20:
            return 100
        elif num_holdings >= 10:
            return 80
        elif num_holdings >= 5:
            return 60
        elif num_holdings >= 3:
            return 40
        else:
            return 20

    def _calculate_overall_risk(self, results: dict[str, dict]) -> str:
        """Calculate overall risk level for the analysis.

        Args:
            results: Risk assessment by symbol

        Returns:
            Overall risk level
        """
        if not results:
            return "insufficient_data"

        risk_scores = [
            score
            for result in results.values()
            if isinstance((score := result.get("risk_score")), int | float)
        ]
        if not risk_scores:
            return "insufficient_data"
        avg_score = sum(risk_scores) / len(risk_scores)

        if avg_score >= 70:
            return "very_high"
        elif avg_score >= 50:
            return "high"
        elif avg_score >= 30:
            return "medium"
        elif avg_score >= 15:
            return "low"
        else:
            return "very_low"
