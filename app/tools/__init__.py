"""Tool registry and tools for the ReAct agent."""

from app.tools.registry import get_all_tools, get_tool, register_tool

__all__ = ["get_all_tools", "get_tool", "register_tool", "register_all_tools"]


def register_all_tools() -> None:
    """Register all available tools. Call this during agent initialization."""
    from app.tools.data.market_data import fetch_stock_data
    from app.tools.data.historical import get_historical_prices
    from app.tools.analysis.auto_tools import (
        analyze_technical,
        analyze_fundamental,
        analyze_sentiment,
        assess_risk,
        get_stock_overview,
    )
    from app.tools.decision.portfolio import calculate_position_size
    from app.tools.report.generate import generate_report

    register_tool(fetch_stock_data)
    register_tool(get_historical_prices)
    register_tool(analyze_technical)
    register_tool(analyze_fundamental)
    register_tool(analyze_sentiment)
    register_tool(assess_risk)
    register_tool(get_stock_overview)
    register_tool(calculate_position_size)
    register_tool(generate_report)
