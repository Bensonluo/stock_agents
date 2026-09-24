"""Decision/position sizing tools. Extracted from app/agents/decision_agent.py"""

from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.analysis.sizing import atr_position_size


class CalculatePositionSizeInput(BaseModel):
    risk_data: dict = Field(description="Risk assessment data from assess_risk")
    scores: dict = Field(default={}, description="Optional analysis scores")
    technical_data: dict = Field(
        default={},
        description=(
            "Optional per-symbol technical analysis; when a symbol carries "
            "indicators.atr_pct here, sizing is volatility-based instead of "
            "risk-band based"
        ),
    )


@tool(args_schema=CalculatePositionSizeInput)
def calculate_position_size(
    risk_data: dict, scores: dict = None, technical_data: dict = None
) -> dict[str, Any]:
    """Calculate recommended position size based on risk assessment.

    Volatility-first: symbols with ATR% in technical_data get sized by the
    shared ATR formula (risk budget / stop distance); the rest keep the
    risk-score bands.
    """
    results = {}
    scores = scores or {}
    technical_data = technical_data or {}

    for symbol, risk in risk_data.items():
        risk_score = risk.get("risk_score", 50)
        risk_level = risk.get("risk_level", "medium")
        max_from_risk = risk.get("position_recommendation", {}).get("max_position_size", 10.0)

        atr_pct = (technical_data.get(symbol) or {}).get("indicators", {}).get("atr_pct")
        vol_size = atr_position_size(atr_pct)

        if vol_size is not None:
            base = vol_size
            rationale = f"Volatility-sized from ATR {atr_pct:.2f}%/day"
        else:
            if risk_score >= 70:
                base = 2.0
            elif risk_score >= 50:
                base = 5.0
            elif risk_score >= 30:
                base = 10.0
            elif risk_score >= 15:
                base = 15.0
            else:
                base = 20.0
            rationale = f"Based on risk score {risk_score}/100"

        final = min(base, max_from_risk)
        results[symbol] = {
            "symbol": symbol,
            "position_size": final,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "rationale": rationale,
        }

    return results
