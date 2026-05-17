"""Decision/position sizing tools. Extracted from app/agents/decision_agent.py"""

from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field


class CalculatePositionSizeInput(BaseModel):
    risk_data: dict = Field(description="Risk assessment data from assess_risk")
    scores: dict = Field(default={}, description="Optional analysis scores")


@tool(args_schema=CalculatePositionSizeInput)
def calculate_position_size(risk_data: dict, scores: dict = None) -> dict[str, Any]:
    """Calculate recommended position size based on risk assessment."""
    results = {}
    scores = scores or {}

    for symbol, risk in risk_data.items():
        risk_score = risk.get("risk_score", 50)
        risk_level = risk.get("risk_level", "medium")
        max_from_risk = risk.get("position_recommendation", {}).get("max_position_size", 10.0)

        if risk_score >= 70: base = 2.0
        elif risk_score >= 50: base = 5.0
        elif risk_score >= 30: base = 10.0
        elif risk_score >= 15: base = 15.0
        else: base = 20.0

        final = min(base, max_from_risk)
        results[symbol] = {
            "symbol": symbol,
            "position_size": final,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "rationale": f"Based on risk score {risk_score}/100",
        }

    return results
