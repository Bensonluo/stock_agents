"""Risk assessment agent for evaluating investment risks.

Per-symbol metrics are computed by the shared engine path
(``app/tools/risk/assessment.assess_symbol`` over ``app/analysis/risk``) —
this agent owns only pipeline orchestration and the portfolio-level summary,
so the LangGraph pipeline and the ReAct tools report identical numbers.
"""

from datetime import datetime
from typing import Any

from app.agents.base import StatelessAgent
from app.analysis.regime import classify_market_regime
from app.analysis.risk import correlation_matrix
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
            # Histories of the names actually assessed — the correlation view
            # must describe the same portfolio as the score aggregation.
            histories = {
                symbol: data["historical_data"]
                for symbol, data in market_data.items()
                if symbol in results
                and isinstance(data.get("historical_data"), dict)
                and data["historical_data"]
            }
            portfolio_risk = self._assess_portfolio_risk(results, histories)

        return {
            "risk_by_symbol": results,
            "portfolio_risk": portfolio_risk,
            "market_regime": self._market_regime(market_data),
            "overall_risk_level": self._calculate_overall_risk(results),
            "timestamp": datetime.now().isoformat(),
        }

    def _market_regime(self, market_data: dict[str, Any]) -> dict[str, Any] | None:
        """Classify the market behind the run from its benchmark series.

        The data layer attaches ``benchmark_historical_data`` to every
        symbol of the market (iteration 31) — same market within a run,
        so the first available series speaks for all of them. Pure
        annotation: nothing downstream reads it into a score yet.
        """
        for data in market_data.values():
            benchmark = data.get("benchmark_historical_data")
            if not isinstance(benchmark, dict):
                continue
            closes = benchmark.get("close")
            if isinstance(closes, list) and closes:
                return classify_market_regime(closes)
        return None

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

    def _assess_portfolio_risk(
        self, results: dict[str, dict], histories: dict[str, dict] | None = None
    ) -> dict[str, Any]:
        """Assess portfolio-level risk.

        Args:
            results: Risk assessment by symbol
            histories: Per-symbol price history (dates/close) for correlations;
                without it the correlation view degrades to insufficient_data.

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

        # Pairwise correlations across the analyzed names — the holdings-count
        # tier alone cannot tell five tech names from five cross-sector names.
        correlations = (
            correlation_matrix(histories)
            if histories
            else {"status": "insufficient_data", "pairs": {}}
        )
        pairs = correlations.get("pairs") or {}
        avg_correlation = (
            sum(pairs.values()) / len(pairs)
            if correlations.get("status") == "available" and pairs
            else None
        )

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
            "diversification_score": self._calculate_diversification_score(
                results, avg_correlation
            ),
            "correlations": correlations,
            "avg_pairwise_correlation": (
                round(avg_correlation, 4) if avg_correlation is not None else None
            ),
        }

    def _calculate_diversification_score(
        self, results: dict[str, dict], avg_correlation: float | None = None
    ) -> int:
        """Calculate diversification score (0-100).

        The holdings-count tier is the ceiling; measured average pairwise
        correlation discounts it — perfectly correlated names diversify
        nothing (0), negative correlation earns the full tier. Without
        correlation evidence the count tier stands (legacy behavior).

        Args:
            results: Risk assessment by symbol
            avg_correlation: Mean of pairwise return correlations, when known

        Returns:
            Diversification score (0-100)
        """
        num_holdings = len(results)

        if num_holdings >= 20:
            score = 100.0
        elif num_holdings >= 10:
            score = 80.0
        elif num_holdings >= 5:
            score = 60.0
        elif num_holdings >= 3:
            score = 40.0
        else:
            score = 20.0

        if avg_correlation is not None:
            score = max(0.0, min(100.0, score * (1.0 - avg_correlation)))
        return round(score)

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
