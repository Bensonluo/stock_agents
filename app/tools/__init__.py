"""Tool registry and tools for the ReAct agent."""

from app.tools.registry import get_all_tools, get_tool, register_tool

__all__ = ["get_all_tools", "get_tool", "register_tool", "register_all_tools"]


def register_all_tools() -> None:
    """Register all available tools. Call this during agent initialization."""
    from app.tools.data.market_data import fetch_stock_data
    from app.tools.data.historical import get_historical_prices
    from app.tools.analysis.technical import analyze_technical
    from app.tools.analysis.fundamental import analyze_fundamental
    from app.tools.analysis.sentiment import analyze_sentiment
    from app.tools.risk.assessment import assess_risk
    from app.tools.decision.portfolio import calculate_position_size
    from app.tools.report.generate import generate_report

    register_tool(fetch_stock_data)
    register_tool(get_historical_prices)
    register_tool(analyze_technical)
    register_tool(analyze_fundamental)
    register_tool(analyze_sentiment)
    register_tool(assess_risk)
    register_tool(calculate_position_size)
    register_tool(generate_report)
