"""Fundamental analysis tool over the shared scoring module."""

from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.analysis.fundamental import scoring
from app.analysis.fundamental.scoring import analyze_fundamental_scoring

# Backwards-compatible aliases for callers importing the historical names.
_analyze_financial_health = scoring._analyze_financial_health
_analyze_growth = scoring._analyze_growth
_analyze_profitability = scoring._analyze_profitability
_analyze_valuation = scoring._analyze_valuation
_calculate_overall_score = scoring._calculate_overall_score
_recommendation = scoring._recommendation
_score_to_rating = scoring._score_to_rating

__all__ = ["analyze_fundamental"]


class AnalyzeFundamentalInput(BaseModel):
    financial_data: dict = Field(description="Financial data from fetch_stock_data")
    market_data: dict = Field(default={}, description="Market data for additional context")


@tool(args_schema=AnalyzeFundamentalInput)
def analyze_fundamental(financial_data: dict, market_data: dict = None) -> dict[str, Any]:
    """Evaluate financial health, profitability, and valuation."""
    return analyze_fundamental_scoring(financial_data, market_data)
