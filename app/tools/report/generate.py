"""Report generation tool. Extracted from app/agents/report_agent.py"""

from datetime import datetime
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field


class GenerateReportInput(BaseModel):
    data: dict = Field(description="All analysis data to compile into a report")


@tool(args_schema=GenerateReportInput)
def generate_report(data: dict) -> dict[str, Any]:
    """Generate a structured investment analysis report.

    This is the FINAL tool you should call. It compiles all analysis results
    into a comprehensive report.

    Args:
        data: Dictionary containing all analysis results:
            - query: Original user query
            - symbols: List of analyzed symbols
            - market_data: Market data
            - technical_analysis: Technical analysis results
            - fundamental_analysis: Fundamental analysis results
            - sentiment_analysis: Sentiment analysis results
            - risk_assessment: Risk assessment results
            - decision: Decision/sizing results

    Returns:
        Structured report with executive summary and sections.
    """
    query = data.get("query", "")
    symbols = data.get("symbols", [])

    sections = {
        "overview": _overview(data),
        "technical_analysis": _technical_section(data),
        "fundamental_analysis": _fundamental_section(data),
        "sentiment_analysis": _sentiment_section(data),
        "risk_analysis": _risk_section(data),
        "recommendations": _recommendations_section(data),
    }

    return {
        "title": _title(query, symbols),
        "generated_at": datetime.now().isoformat(),
        "executive_summary": _executive_summary(data, sections),
        "sections": sections,
        "metadata": {
            "symbols": symbols,
            "query": query,
        },
    }


def _title(query: str, symbols: list) -> str:
    if symbols:
        if len(symbols) == 1:
            return f"Investment Research Report: {symbols[0]}"
        return f"Investment Research Report: {', '.join(symbols[:3])}{'...' if len(symbols) > 3 else ''}"
    return "Investment Research Report"


def _overview(data: dict) -> dict:
    symbols = data.get("symbols", [])
    market = data.get("market_data", {})
    return {
        "symbols_analyzed": symbols,
        "analysis_date": datetime.now().strftime("%Y-%m-%d"),
        "market_summary": {
            s: {
                "company_name": market.get(s, {}).get("company_name"),
                "current_price": market.get(s, {}).get("current_price"),
                "sector": market.get(s, {}).get("sector"),
            }
            for s in symbols
        },
    }


def _technical_section(data: dict) -> dict:
    technical = data.get("technical_analysis", {})
    bullish = sum(1 for a in technical.values() if a.get("sentiment", {}).get("score", 0) > 20)
    bearish = sum(1 for a in technical.values() if a.get("sentiment", {}).get("score", 0) < -20)

    outlook = "bullish" if bullish > bearish else "bearish" if bearish > bullish else "neutral"

    return {
        "by_symbol": {
            s: {
                "trend": a.get("signals", {}).get("trend", "neutral"),
                "rsi": a.get("signals", {}).get("rsi", "neutral"),
                "sentiment_score": a.get("sentiment", {}).get("score", 0),
            }
            for s, a in technical.items()
        },
        "overall_outlook": outlook,
    }


def _fundamental_section(data: dict) -> dict:
    fundamental = data.get("fundamental_analysis", {})
    total = sum(a.get("overall_score", {}).get("score", 50) for a in fundamental.values())
    avg = total / len(fundamental) if fundamental else 50

    rating = "buy" if avg >= 65 else "hold" if avg >= 35 else "sell"

    return {
        "by_symbol": {
            s: {
                "overall_score": a.get("overall_score", {}).get("score", 50),
                "recommendation": a.get("recommendation", "hold"),
            }
            for s, a in fundamental.items()
        },
        "overall_rating": rating,
    }


def _sentiment_section(data: dict) -> dict:
    sentiment = data.get("sentiment_analysis", {})
    by_symbol = sentiment.get("sentiment_by_symbol", {})

    return {
        "by_symbol": {
            s: {
                "sentiment": a.get("sentiment", "neutral"),
                "score": a.get("score", 0),
            }
            for s, a in by_symbol.items()
        },
        "overall": sentiment.get("overall_sentiment", {}),
    }


def _risk_section(data: dict) -> dict:
    risk = data.get("risk_assessment", {})
    by_symbol = risk.get("risk_by_symbol", risk)

    return {
        "by_symbol": {
            s: {
                "risk_level": a.get("risk_level", "medium"),
                "risk_score": a.get("risk_score", 50),
            }
            for s, a in by_symbol.items()
        },
        "overall_risk": risk.get("overall_risk_level", "medium"),
    }


def _recommendations_section(data: dict) -> dict:
    decisions = data.get("decision", {})
    if isinstance(decisions, dict) and "decisions" in decisions:
        decisions = decisions["decisions"]

    return {
        "by_symbol": {
            s: {
                "action": d.get("action", "hold"),
                "confidence": d.get("confidence", 0),
            }
            for s, d in decisions.items()
        },
        "portfolio_actions": [
            {"symbol": s, "action": d["action"]}
            for s, d in decisions.items()
            if "buy" in d.get("action", "")
        ],
    }


def _executive_summary(data: dict, sections: dict) -> str:
    symbols = data.get("symbols", [])
    decisions = data.get("decision", {})
    if isinstance(decisions, dict) and "decisions" in decisions:
        decisions = decisions["decisions"]

    parts = []
    if len(symbols) == 1:
        parts.append(f"This report analyzes {symbols[0]} across technical, fundamental, sentiment, and risk dimensions.")
    else:
        parts.append(f"This report analyzes {len(symbols)} stocks.")

    if decisions:
        top = max(decisions.items(), key=lambda x: x[1].get("score", 0) if isinstance(x[1], dict) else 0)
        if isinstance(top[1], dict):
            parts.append(f"Top pick: {top[0]} ({top[1].get('action', 'hold')}) with {top[1].get('confidence', 0):.0f}% confidence.")

    risk = sections.get("risk_analysis", {})
    parts.append(f"Overall risk level: {risk.get('overall_risk', 'medium')}.")

    tech = sections.get("technical_analysis", {})
    parts.append(f"Technical outlook: {tech.get('overall_outlook', 'neutral')}.")

    return " ".join(parts)
