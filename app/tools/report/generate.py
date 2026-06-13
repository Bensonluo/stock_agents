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
        "metadata": {"symbols": symbols, "query": query},
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
            s: {"sentiment": a.get("sentiment", "neutral"), "score": a.get("score", 0)}
            for s, a in by_symbol.items()
        },
        "overall": sentiment.get("overall_sentiment", {}),
    }


def _risk_section(data: dict) -> dict:
    risk = data.get("risk_assessment", {})
    return {
        "by_symbol": {
            s: {"risk_level": a.get("risk_level", "medium"), "risk_score": a.get("risk_score", 50)}
            for s, a in risk.items()
        },
        "overall_risk": "medium",
    }


def _risk_to_score(risk_level: str) -> int:
    """Map risk level (low..very_high) to 0..100 (lower = safer)."""
    return {
        "very_low": 10, "low": 30, "medium": 50, "high": 75, "very_high": 95,
    }.get(str(risk_level).lower(), 50)


def _derive_recommendation(
    symbol: str,
    fundamental: dict,
    technical: dict,
    sentiment: dict,
    risk: dict,
) -> dict:
    """Rule-based action synthesis that ALWAYS agrees with the analysis.

    Combines fundamental score (0-100), technical sentiment (-100..100),
    sentiment score (-100..100), and risk level into a single action.
    The LLM cannot override this — guarantees the report is internally
    consistent (e.g. fundamental=strong_sell ⇒ action=sell, not "add").
    """
    fund_score_raw = fundamental.get("overall_score", 50)
    if isinstance(fund_score_raw, dict):
        fund_score = float(fund_score_raw.get("score", 50) or 50)
    else:
        fund_score = float(fund_score_raw or 50)
    fund_rec = str(fundamental.get("recommendation", "hold")).lower()
    tech_trend = str(technical.get("trend", "neutral")).lower()
    tech_score = float(technical.get("sentiment_score", 0) or 0)
    sent_score = float(sentiment.get("score", 0) or 0)
    risk_level = str(risk.get("risk_level", "medium")).lower()
    risk_penalty = _risk_to_score(risk_level)

    # Normalize technical & sentiment to 0-100, then weighted-blend.
    tech_norm = max(0.0, min(100.0, (tech_score + 100) / 2))
    sent_norm = max(0.0, min(100.0, (sent_score + 100) / 2))
    risk_norm = 100 - risk_penalty  # higher = safer

    combined = (
        fund_score * 0.45
        + tech_norm * 0.30
        + sent_norm * 0.15
        + risk_norm * 0.10
    )

    if combined >= 70:
        action = "buy"
        confidence = round(min(0.9, combined / 100), 2)
    elif combined >= 55:
        action = "add"
        confidence = round(0.55 + (combined - 55) / 100, 2)
    elif combined >= 42:
        action = "hold"
        confidence = 0.5
    elif combined >= 28:
        action = "reduce"
        confidence = round(0.55 + (42 - combined) / 100, 2)
    else:
        action = "sell"
        confidence = round(min(0.9, (100 - combined) / 100), 2)

    # Build human-readable reasoning in the same language as the query will be
    # handled by _executive_summary; here we keep it English (canonical).
    reasoning = (
        f"Composite score {combined:.0f}/100 "
        f"(fundamental {fund_score:.0f}/{fund_rec}, "
        f"technical {tech_trend}/{tech_score:+.0f}, "
        f"sentiment {sent_score:+.0f}, risk {risk_level})"
    )

    return {
        "action": action,
        "confidence": confidence,
        "composite_score": round(combined, 1),
        "reasoning": reasoning,
    }


def _recommendations_section(data: dict) -> dict:
    """Derive per-symbol recommendation from the analysis sections, not from
    a separate `decision` field the LLM may forget to fill. Fall back to the
    LLM's `decision` only if absolutely no analysis data is available.
    """
    symbols = data.get("symbols", []) or []
    fundamental = data.get("fundamental_analysis", {}) or {}
    technical = data.get("technical_analysis", {}) or {}
    sentiment = data.get("sentiment_analysis", {}) or {}
    risk = data.get("risk_assessment", {}) or {}

    by_symbol: dict[str, dict] = {}
    for s in symbols:
        f = (fundamental.get(s) or {})
        t = (technical.get(s) or {})
        sent_block = (sentiment.get("sentiment_by_symbol", {}) or {}).get(s) or (sentiment.get(s) or {})
        r = (risk.get(s) or {})

        if not any([f, t, sent_block, r]):
            by_symbol[s] = {
                "action": "hold",
                "confidence": 0.3,
                "composite_score": 50.0,
                "reasoning": "Insufficient analysis data to derive a recommendation",
            }
            continue

        by_symbol[s] = _derive_recommendation(s, f, t, sent_block, r)

    portfolio_actions = [
        {"symbol": s, "action": v["action"], "confidence": v["confidence"]}
        for s, v in by_symbol.items()
        if v["action"] in ("buy", "add")
    ]
    sells = [
        {"symbol": s, "action": v["action"], "confidence": v["confidence"]}
        for s, v in by_symbol.items()
        if v["action"] in ("sell", "reduce")
    ]
    return {
        "by_symbol": by_symbol,
        "portfolio_actions": portfolio_actions,
        "sell_actions": sells,
    }


# Translations of recommendation labels.
_RECOMMEND_LABELS = {
    "en": {
        "buy": "BUY", "add": "ADD", "hold": "HOLD", "reduce": "REDUCE", "sell": "SELL",
        "verdict": "Recommendation", "composite": "composite score", "based_on": "based on",
        "fund": "fundamental", "tech": "technical", "sent": "sentiment", "risk": "risk",
    },
    "zh": {
        "buy": "买入", "add": "加仓", "hold": "持有", "reduce": "减仓", "sell": "卖出",
        "verdict": "投资建议", "composite": "综合评分", "based_on": "基于",
        "fund": "基本面", "tech": "技术面", "sent": "情绪", "risk": "风险",
    },
}


def _detect_lang(text: str) -> str:
    """Return 'zh' if the text contains CJK characters, else 'en'."""
    if not text:
        return "en"
    for ch in text:
        if "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿":
            return "zh"
    return "en"


def _executive_summary(data: dict, sections: dict) -> str:
    """Build a concise, actionable summary. Language matches the query.
    Format: '<SYMBOL> <price>: <action> — <reasoning>'. Risk level appended.
    """
    symbols = data.get("symbols", []) or []
    query = data.get("query", "")
    lang = _detect_lang(query)
    L = _RECOMMEND_LABELS[lang]

    risk_section = sections.get("risk_analysis", {}) or {}
    overall_risk = risk_section.get("overall_risk", "medium")
    rec_section = sections.get("recommendations", {}) or {}
    by_symbol = rec_section.get("by_symbol", {}) or {}
    market_summary = (sections.get("overview", {}) or {}).get("market_summary", {}) or {}
    market = data.get("market_data", {}) or {}  # fallback only

    if not symbols:
        return "分析完成。" if lang == "zh" else "Analysis complete."

    parts: list[str] = []
    for s in symbols:
        rec = by_symbol.get(s, {}) or {}
        action = rec.get("action", "hold")
        confidence = rec.get("confidence", 0.5)
        composite = rec.get("composite_score")
        # Prefer sections.overview.market_summary[s] (built by the LLM tool
        # call path), fall back to data["market_data"][s] (what the LLM
        # assembles from raw tool results).
        m = market_summary.get(s) or market.get(s, {}) or {}
        price = m.get("current_price")
        company = m.get("company_name") or s

        price_str = f"${price:.2f}" if isinstance(price, (int, float)) else "N/A"
        if lang == "zh":
            parts.append(
                f"{company}({s}) 当前价 {price_str} — 建议: {L[action]} "
                f"(置信度 {confidence:.0%}{', ' + L['composite'] + ' ' + f'{composite:.0f}/100' if composite is not None else ''})。"
            )
        else:
            parts.append(
                f"{company} ({s}) @ {price_str} — {L['verdict']}: {L[action]} "
                f"(confidence {confidence:.0%}{', ' + L['composite'] + ' ' + f'{composite:.0f}/100' if composite is not None else ''})."
            )

    if lang == "zh":
        risk_label = {"very_low": "极低", "low": "低", "medium": "中", "high": "高", "very_high": "极高"}.get(overall_risk, overall_risk)
        parts.append(f"整体{L['risk']}水平: {risk_label}。")
    else:
        parts.append(f"Overall {L['risk']}: {overall_risk}.")

    return " ".join(parts)
