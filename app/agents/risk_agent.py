"""Risk assessment agent for evaluating investment risks."""

from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

from app.agents.base import StatelessAgent
from app.orchestration.state import AgentState
from app.utils.logging import get_logger

logger = get_logger(__name__)


class RiskAssessmentAgent(StatelessAgent):
    """Agent responsible for risk assessment of stock investments.

    This agent:
    - Calculates market risk metrics (Beta, VaR, volatility)
    - Assesses portfolio risk
    - Evaluates downside risk
    - Provides risk warnings
    - Suggests position sizing based on risk
    """

    async def process(self, state: AgentState) -> Dict[str, Any]:
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

    async def _assess_risk(self, symbol: str, data: Dict) -> Dict[str, Any]:
        """Assess risk for a single symbol.

        Args:
            symbol: Stock symbol
            data: Market data dictionary

        Returns:
            Risk assessment dictionary
        """
        hist_data = data.get("historical_data")
        if not hist_data:
            return self._minimal_risk_assessment(data)

        # Convert to arrays
        closes = np.array(hist_data.get("close", []))

        if len(closes) < 20:
            return self._minimal_risk_assessment(data)

        # Calculate returns
        returns = np.diff(closes) / closes[:-1]

        # Calculate risk metrics
        volatility = self._calculate_volatility(returns)
        var_95 = self._calculate_var(returns, confidence=0.95)
        var_99 = self._calculate_var(returns, confidence=0.99)
        max_drawdown = self._calculate_max_drawdown(closes)
        downside_risk = self._calculate_downside_risk(returns)

        # Calculate beta (simplified, using S&P 500 as proxy)
        beta = self._estimate_beta(returns)

        # Risk score
        risk_score = self._calculate_risk_score({
            "volatility": volatility,
            "max_drawdown": max_drawdown,
            "var_95": var_95,
            "beta": beta,
        })

        # Risk level
        risk_level = self._risk_score_to_level(risk_score)

        # Position size recommendation
        position_size = self._calculate_position_size(risk_score)

        # Stop loss recommendation
        stop_loss = self._calculate_stop_loss(closes, volatility)

        return {
            "symbol": symbol,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "metrics": {
                "volatility": volatility,
                "volatility_annualized": float(volatility * np.sqrt(252)),
                "var_95": var_95,
                "var_99": var_99,
                "max_drawdown": max_drawdown,
                "downside_risk": downside_risk,
                "beta": beta,
            },
            "position_recommendation": {
                "max_position_size": position_size,
                "stop_loss_percentage": stop_loss,
                "risk_reward_ratio": self._estimate_risk_reward(closes, volatility),
            },
            "warnings": self._generate_risk_warnings(risk_level, volatility, max_drawdown),
        }

    def _calculate_volatility(self, returns: np.ndarray, annualize: bool = False) -> float:
        """Calculate volatility (standard deviation of returns).

        Args:
            returns: Array of returns
            annualize: Whether to annualize

        Returns:
            Volatility value
        """
        vol = np.std(returns)
        if annualize:
            vol *= np.sqrt(252)
        return float(vol)

    def _calculate_var(self, returns: np.ndarray, confidence: float = 0.95) -> float:
        """Calculate Value at Risk.

        Args:
            returns: Array of returns
            confidence: Confidence level (0.95 = 95%)

        Returns:
            VaR value (negative number representing potential loss)
        """
        return float(np.percentile(returns, (1 - confidence) * 100))

    def _calculate_max_drawdown(self, prices: np.ndarray) -> float:
        """Calculate maximum drawdown.

        Args:
            prices: Array of prices

        Returns:
            Maximum drawdown as a positive number
        """
        cummax = np.maximum.accumulate(prices)
        drawdown = (cummax - prices) / cummax
        return float(np.max(drawdown))

    def _calculate_downside_risk(self, returns: np.ndarray) -> float:
        """Calculate downside risk (semi-deviation).

        Args:
            returns: Array of returns

        Returns:
            Downside risk value
        """
        negative_returns = returns[returns < 0]
        if len(negative_returns) == 0:
            return 0.0
        return float(np.std(negative_returns))

    def _estimate_beta(self, returns: np.ndarray) -> Optional[float]:
        """Estimate beta (simplified without market data).

        Args:
            returns: Array of returns

        Returns:
            Estimated beta (1.0 as default placeholder)
        """
        # In a real implementation, you would calculate correlation with market
        # For now, return a placeholder
        return 1.0

    def _calculate_risk_score(self, metrics: Dict[str, float]) -> float:
        """Calculate overall risk score (0-100, higher = riskier).

        Args:
            metrics: Dictionary of risk metrics

        Returns:
            Risk score
        """
        score = 0

        # Volatility score (0-30 points)
        vol = metrics.get("volatility", 0)
        if vol >= 0.03:  # >3% daily volatility
            score += 30
        elif vol >= 0.02:
            score += 20
        elif vol >= 0.015:
            score += 10

        # Max drawdown score (0-30 points)
        dd = metrics.get("max_drawdown", 0)
        if dd >= 0.3:  # >30% drawdown
            score += 30
        elif dd >= 0.2:
            score += 20
        elif dd >= 0.1:
            score += 10

        # VaR score (0-20 points)
        var = abs(metrics.get("var_95", 0))
        if var >= 0.05:  # >5% daily VaR
            score += 20
        elif var >= 0.03:
            score += 15
        elif var >= 0.02:
            score += 10

        # Beta score (0-20 points)
        beta = metrics.get("beta", 1)
        if beta >= 1.5:
            score += 20
        elif beta >= 1.2:
            score += 15
        elif beta <= 0.5:
            score += 5

        return min(100, score)

    def _risk_score_to_level(self, score: float) -> str:
        """Convert risk score to risk level.

        Args:
            score: Risk score (0-100)

        Returns:
            Risk level string
        """
        if score >= 70:
            return "very_high"
        elif score >= 50:
            return "high"
        elif score >= 30:
            return "medium"
        elif score >= 15:
            return "low"
        else:
            return "very_low"

    def _calculate_position_size(self, risk_score: float) -> float:
        """Calculate recommended position size based on risk.

        Args:
            risk_score: Risk score (0-100)

        Returns:
            Maximum position size as percentage of portfolio
        """
        # Higher risk = smaller position
        if risk_score >= 70:
            return 2.0  # Max 2% of portfolio
        elif risk_score >= 50:
            return 5.0
        elif risk_score >= 30:
            return 10.0
        elif risk_score >= 15:
            return 15.0
        else:
            return 20.0

    def _calculate_stop_loss(self, prices: np.ndarray, volatility: float) -> float:
        """Calculate recommended stop loss percentage.

        Args:
            prices: Array of prices
            volatility: Daily volatility

        Returns:
            Stop loss percentage (positive number)
        """
        # Use 2x daily volatility as stop loss
        # Convert to percentage and multiply for position
        return float(volatility * 2 * 100)

    def _estimate_risk_reward(self, prices: np.ndarray, volatility: float) -> Optional[float]:
        """Estimate risk/reward ratio.

        Args:
            prices: Array of prices
            volatility: Daily volatility

        Returns:
            Risk/reward ratio or None
        """
        if len(prices) < 20:
            return None

        current = prices[-1]
        avg = np.mean(prices[-20:])

        # Potential upside
        upside = (avg - current) / current if avg > current else 0

        # Risk as 2x volatility
        downside = volatility * 2

        if downside > 0:
            return float(upside / downside) if upside > 0 else 1.0
        return None

    def _generate_risk_warnings(
        self, risk_level: str, volatility: float, max_drawdown: float
    ) -> List[str]:
        """Generate risk warnings.

        Args:
            risk_level: Risk level
            volatility: Daily volatility
            max_drawdown: Maximum drawdown

        Returns:
            List of warning messages
        """
        warnings = []

        if risk_level in ["high", "very_high"]:
            warnings.append("This stock has high risk. Consider smaller position size.")

        if volatility > 0.03:
            warnings.append(f"High daily volatility ({volatility*100:.1f}%). Expect large price swings.")

        if max_drawdown > 0.3:
            warnings.append(f"History of deep drawdowns ({max_drawdown*100:.1f}%). Risk of significant loss.")

        if risk_level == "very_high":
            warnings.append("Consider using stop-loss orders to limit potential losses.")

        return warnings

    def _minimal_risk_assessment(self, data: Dict) -> Dict[str, Any]:
        """Provide minimal risk assessment when insufficient data.

        Args:
            data: Market data

        Returns:
            Basic risk assessment
        """
        return {
            "symbol": data.get("symbol", ""),
            "risk_score": 50,
            "risk_level": "medium",
            "metrics": {},
            "position_recommendation": {
                "max_position_size": 10.0,
            },
            "warnings": ["Insufficient data for detailed risk assessment"],
        }

    def _assess_portfolio_risk(self, results: Dict[str, Dict]) -> Dict[str, Any]:
        """Assess portfolio-level risk.

        Args:
            results: Risk assessment by symbol

        Returns:
            Portfolio risk summary
        """
        # Calculate average risk metrics
        risk_scores = [r.get("risk_score", 50) for r in results.values()]
        avg_risk_score = sum(risk_scores) / len(risk_scores) if risk_scores else 50

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
            },
            "diversification_score": self._calculate_diversification_score(results),
        }

    def _calculate_diversification_score(self, results: Dict[str, Dict]) -> float:
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

    def _calculate_overall_risk(self, results: Dict[str, Dict]) -> str:
        """Calculate overall risk level for the analysis.

        Args:
            results: Risk assessment by symbol

        Returns:
            Overall risk level
        """
        if not results:
            return "medium"

        risk_scores = [r.get("risk_score", 50) for r in results.values()]
        avg_score = sum(risk_scores) / len(risk_scores)

        return self._risk_score_to_level(avg_score)
