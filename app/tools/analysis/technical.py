"""Technical analysis tool over the canonical daily engine.

The formulas live in ``app/analysis/technical/daily.py``; this module keeps
only the multi-symbol tool wrapper plus backwards-compatible aliases (ReAct's
``auto_tools`` imports the private names).
"""

from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.analysis.technical import (
    analyze_daily,
    calculate_indicators,
    calculate_sentiment,
    find_support_resistance,
    generate_signals,
    to_dataframe,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Backwards-compatible aliases for callers importing the historical private names.
_to_dataframe = to_dataframe
_calculate_indicators = calculate_indicators
_generate_signals = generate_signals
_find_support_resistance = find_support_resistance
_calculate_sentiment = calculate_sentiment


class AnalyzeTechnicalInput(BaseModel):
    market_data: dict = Field(description="Market data from fetch_stock_data")


@tool(args_schema=AnalyzeTechnicalInput)
def analyze_technical(market_data: dict) -> dict[str, Any]:
    """Compute technical indicators (RSI, MACD, Bollinger Bands, support/resistance)."""
    results = {}

    for symbol, data in market_data.items():
        hist = data.get("historical_data")
        if not hist:
            continue
        try:
            results[symbol] = analyze_daily(
                hist,
                symbol=symbol,
                current_price=data.get("current_price"),
                source="market_data_history",
            )
        except Exception as e:
            logger.error(f"Technical analysis failed for {symbol}: {e}")

    return results
