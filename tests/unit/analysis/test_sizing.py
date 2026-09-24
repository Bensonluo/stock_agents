"""Volatility-normalized position sizing.

Conviction bands sized positions by signal strength, not by how much
damage a normal day could do; ATR sizing risks a fixed slice of the
portfolio per trade (risk budget / stop distance). These tests pin the
formula, its degradation to the old bands, and both call paths using the
ONE shared implementation.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from app.analysis.sizing import atr_position_size
from app.tools.decision.portfolio import calculate_position_size


class TestAtrPositionSize:
    def test_typical_volatility(self):
        # 2xATR stop at 4% -> 1% risk budget / 4% = 25% weight
        assert atr_position_size(2.0) == 20.0  # capped at ceiling

    def test_high_volatility_shrinks_position(self):
        # 2xATR stop at 10% -> 1% / 10% = 10%
        assert atr_position_size(5.0) == 10.0

    def test_extreme_volatility_tiny_position(self):
        assert atr_position_size(40.0) == 1.25

    def test_calm_stock_hits_ceiling(self):
        # 2xATR stop at 2% -> 50% weight, but ceiling caps at 20
        assert atr_position_size(1.0) == 20.0

    def test_unusable_inputs_return_none(self):
        assert atr_position_size(None) is None
        assert atr_position_size(0) is None
        assert atr_position_size(-3.0) is None
        assert atr_position_size("2.0") is None

    def test_custom_budget_and_multiple(self):
        # 3% budget, 3x stop, ATR 3% -> 3 / 9 * 100 = 33.3 -> ceiling 20
        assert atr_position_size(3.0, risk_budget_pct=3.0, stop_multiple=3.0) == 20.0
        # 3% budget, 3x stop, ATR 10% -> 3 / 30 * 100 = 10
        assert atr_position_size(10.0, risk_budget_pct=3.0, stop_multiple=3.0) == 10.0


def _load_decision_agent():
    """Load decision_agent with stubbed base/state (package-cycle guard)."""
    base_module = ModuleType("app.agents.base")
    base_module.BaseAgent = type("BaseAgent", (), {})
    base_module.StatelessAgent = type("StatelessAgent", (), {})
    state_module = ModuleType("app.orchestration.state")
    state_module.AgentState = dict
    replaced = {
        name: sys.modules.get(name) for name in ("app.agents.base", "app.orchestration.state")
    }
    sys.modules.update({"app.agents.base": base_module, "app.orchestration.state": state_module})
    try:
        path = Path(__file__).parents[3] / "app" / "agents" / "decision_agent.py"
        spec = importlib.util.spec_from_file_location("decision_agent_sizing", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.modules.update({name: mod for name, mod in replaced.items() if mod is not None})


class TestPipelineDecisionSizing:
    def setup_method(self):
        self.agent = _load_decision_agent().DecisionMakingAgent()

    def test_atr_sizing_overrides_conviction_bands(self):
        # Strong conviction (score 60 -> old band 20) on a volatile name:
        # ATR 5%/day -> 10% position. Volatility wins over conviction.
        result = self.agent._calculate_position_size(
            60.0, {"max_position_size": 25}, {"indicators": {"atr_pct": 5.0}}
        )

        assert result["percentage_of_portfolio"] == 10.0
        assert "Volatility-sized" in result["sizing_rationale"]
        assert "ATR" in result["sizing_rationale"]

    def test_missing_atr_falls_back_to_conviction_bands(self):
        result = self.agent._calculate_position_size(60.0, {"max_position_size": 25}, {})

        assert result["percentage_of_portfolio"] == 20.0
        assert "conviction" in result["sizing_rationale"]

    def test_none_atr_value_falls_back_to_bands(self):
        # Degraded technical blocks carry explicit None, not absent keys.
        result = self.agent._calculate_position_size(
            30.0, {"max_position_size": 25}, {"indicators": {"atr_pct": None}}
        )

        assert result["percentage_of_portfolio"] == 15.0

    def test_no_technical_block_keeps_bands(self):
        result = self.agent._calculate_position_size(30.0, {"max_position_size": 25})

        assert result["percentage_of_portfolio"] == 15.0

    def test_risk_cap_still_binds_over_atr_size(self):
        # ATR says 20 (calm stock), risk agent caps at 8 -> 8.
        result = self.agent._calculate_position_size(
            30.0, {"max_position_size": 8}, {"indicators": {"atr_pct": 1.0}}
        )

        assert result["percentage_of_portfolio"] == 8.0


class TestReActToolSizing:
    def _risk(self, risk_score=20):
        # risk_score 20 -> old band base 15.0
        return {
            "TEST": {
                "risk_score": risk_score,
                "risk_level": "medium",
                "position_recommendation": {"max_position_size": 25.0},
            }
        }

    def test_tool_uses_shared_atr_formula_when_technical_present(self):
        result = calculate_position_size.invoke(
            {
                "risk_data": self._risk(),
                "technical_data": {"TEST": {"indicators": {"atr_pct": 5.0}}},
            }
        )

        assert result["TEST"]["position_size"] == 10.0
        assert "Volatility-sized" in result["TEST"]["rationale"]

    def test_tool_keeps_risk_bands_without_technical_data(self):
        result = calculate_position_size.invoke({"risk_data": self._risk()})

        assert result["TEST"]["position_size"] == 15.0
        assert "risk score" in result["TEST"]["rationale"]

    def test_pipeline_and_react_agree_given_the_same_atr(self):
        # Path parity: same ATR input -> same sized position on both paths.
        react = calculate_position_size.invoke(
            {
                "risk_data": self._risk(),
                "technical_data": {"TEST": {"indicators": {"atr_pct": 4.0}}},
            }
        )
        agent = _load_decision_agent().DecisionMakingAgent()
        pipeline = agent._calculate_position_size(
            30.0, {"max_position_size": 25.0}, {"indicators": {"atr_pct": 4.0}}
        )

        assert react["TEST"]["position_size"] == pipeline["percentage_of_portfolio"]
