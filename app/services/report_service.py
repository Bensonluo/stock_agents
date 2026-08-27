"""ReportService — the single implementation of report section building.

Before V2 the pipeline (``app/agents/report_agent.py``) and the ReAct path
(``app/tools/report/generate.py``) each maintained their own section builders
over slightly different input shapes. Both now delegate here. The service
normalizes the two input shapes once, then builds the richest union of the
sections; LLMs only narrate, every number comes from the analysis data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.analysis.fundamental import compact_quality_view
from app.analysis.technical import compact_weekly_view
from app.analysis.valuation import compact_valuation_view


class ReportService:
    """Builds the legacy-shaped report dict consumed by API and frontend."""

    @classmethod
    def build_sections(cls, data: dict[str, Any]) -> dict[str, Any]:
        """The report sections from normalized analysis data."""
        c = cls._normalize(data)
        sections = {
            "overview": cls._overview(c),
            "technical_analysis": cls._technical(c),
            "fundamental_analysis": cls._fundamental(c),
            "sentiment_analysis": cls._sentiment(c),
            "risk_analysis": cls._risk(c),
            "recommendations": cls._recommendations(c),
        }
        synthesis = cls._synthesis(c)
        if synthesis:
            sections["research_synthesis"] = synthesis
        evidence_index = cls._evidence_index(c)
        if evidence_index:
            sections["evidence_index"] = evidence_index
        return sections

    @classmethod
    def build_report(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Full deterministic report: title, executive summary, sections."""
        sections = cls.build_sections(data)
        return {
            "title": cls.build_title(data.get("query", ""), data.get("symbols") or []),
            "generated_at": datetime.now().isoformat(),
            "executive_summary": cls.executive_summary(data, sections),
            "sections": sections,
            "metadata": {
                "symbols": data.get("symbols") or [],
                "query": data.get("query", ""),
            },
        }

    # ------------------------------------------------------------------
    # Input normalization
    # ------------------------------------------------------------------

    @classmethod
    def _normalize(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Merge pipeline-state and ReAct data shapes into one canonical dict."""
        market = data.get("market_data") or {}
        symbols = list(data.get("symbols") or []) or list(market.keys())

        risk = data.get("risk_assessment") or {}
        portfolio_risk: dict[str, Any] = {}
        overall_risk_level = "medium"
        if "risk_by_symbol" in risk:  # pipeline shape nests per-symbol data
            portfolio_risk = risk.get("portfolio_risk") or {}
            overall_risk_level = risk.get("overall_risk_level", "medium")
            risk = risk.get("risk_by_symbol") or {}

        sentiment = data.get("sentiment_analysis") or {}
        overall_sentiment = sentiment.get("overall_sentiment", {})
        if "sentiment_by_symbol" in sentiment:
            sentiment = sentiment.get("sentiment_by_symbol") or {}

        return {
            "query": data.get("query", ""),
            "symbols": symbols,
            "market_data": market,
            "technical_analysis": data.get("technical_analysis") or {},
            "fundamental_analysis": data.get("fundamental_analysis") or {},
            "sentiment_flat": sentiment,
            "overall_sentiment": overall_sentiment,
            "risk_flat": risk,
            "portfolio_risk": portfolio_risk,
            "overall_risk_level": overall_risk_level,
            "decisions": data.get("decisions") or {},
            "research_synthesis": data.get("research_synthesis") or {},
        }

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    @classmethod
    def _overview(cls, c: dict[str, Any]) -> dict[str, Any]:
        market = c["market_data"]
        summary: dict[str, Any] = {}
        for symbol in c["symbols"]:
            mkt = market.get(symbol, {})
            summary[symbol] = {
                "company_name": mkt.get("company_name"),
                "current_price": mkt.get("current_price"),
                "change": mkt.get("change"),
                "change_percent": mkt.get("change_percent"),
                "volume": mkt.get("volume"),
                "sector": mkt.get("sector"),
                "as_of": mkt.get("as_of"),
            }
        return {
            "symbols_analyzed": c["symbols"],
            "analysis_date": datetime.now().strftime("%Y-%m-%d"),
            "market_summary": summary,
        }

    @classmethod
    def _technical(cls, c: dict[str, Any]) -> dict[str, Any]:
        bullish = bearish = 0
        by_symbol: dict[str, Any] = {}
        for symbol, analysis in c["technical_analysis"].items():
            sentiment = analysis.get("sentiment", {})
            score = sentiment.get("score", 0)
            signals = analysis.get("signals", {})
            by_symbol[symbol] = {
                "trend": signals.get("trend", "neutral"),
                "rsi": signals.get("rsi", "neutral"),
                "macd": signals.get("macd", "neutral"),
                "support": analysis.get("support", {}),
                "resistance": analysis.get("resistance", {}),
                "sentiment_score": score,
                "weekly_trend": compact_weekly_view(analysis.get("weekly_sma")),
            }
            if score > 20:
                bullish += 1
            elif score < -20:
                bearish += 1

        if bullish > bearish:
            outlook = "bullish"
        elif bearish > bullish:
            outlook = "bearish"
        else:
            outlook = "neutral"
        return {"by_symbol": by_symbol, "overall_outlook": outlook}

    @classmethod
    def _fundamental(cls, c: dict[str, Any]) -> dict[str, Any]:
        by_symbol: dict[str, Any] = {}
        total_score = 0.0
        for symbol, analysis in c["fundamental_analysis"].items():
            overall = analysis.get("overall_score", {})
            if isinstance(overall, dict):
                score = overall.get("score", 50)
                rating = overall.get("rating", "fair")
            else:  # legacy numeric score
                score = overall if isinstance(overall, (int, float)) else 50
                rating = "fair"
            total_score += score
            by_symbol[symbol] = {
                "overall_score": score,
                "rating": rating,
                "recommendation": analysis.get("recommendation", "hold"),
                "profitability": analysis.get("profitability", {}).get("rating", "N/A"),
                "valuation": analysis.get("valuation", {}).get("rating", "N/A"),
                "financial_health": analysis.get("financial_health", {}).get("rating", "N/A"),
                "valuation_scenarios": compact_valuation_view(
                    analysis.get("valuation_scenarios")
                ),
                "quality": compact_quality_view(analysis.get("quality")),
            }

        overall_rating = "hold"
        if c["fundamental_analysis"]:
            avg = total_score / len(c["fundamental_analysis"])
            overall_rating = "buy" if avg >= 65 else "sell" if avg < 35 else "hold"
        return {"by_symbol": by_symbol, "overall_rating": overall_rating}

    @classmethod
    def _sentiment(cls, c: dict[str, Any]) -> dict[str, Any]:
        by_symbol = {
            symbol: {
                "sentiment": analysis.get("sentiment", "neutral"),
                "score": analysis.get("score", 0),
                "trend": analysis.get("trend", "stable"),
                "article_count": analysis.get("article_count", 0),
            }
            for symbol, analysis in c["sentiment_flat"].items()
        }
        return {"by_symbol": by_symbol, "overall": c["overall_sentiment"]}

    @classmethod
    def _risk(cls, c: dict[str, Any]) -> dict[str, Any]:
        by_symbol: dict[str, Any] = {}
        scores: list[float] = []
        for symbol, analysis in c["risk_flat"].items():
            metrics = analysis.get("metrics", {})
            position = analysis.get("position_recommendation", {})
            score = analysis.get("risk_score", 50)
            if isinstance(score, (int, float)):
                scores.append(score)
            by_symbol[symbol] = {
                "risk_level": analysis.get("risk_level", "medium"),
                "risk_score": score,
                "beta": metrics.get("beta"),
                "volatility": metrics.get("volatility_annualized"),
                "max_position_size": position.get("max_position_size"),
                "warnings": analysis.get("warnings", []),
            }

        overall = c["overall_risk_level"]
        if c["overall_risk_level"] == "medium" and scores:
            avg = sum(scores) / len(scores)
            overall = "high" if avg >= 60 else "low" if avg < 30 else "medium"
        return {
            "by_symbol": by_symbol,
            "portfolio_risk": c["portfolio_risk"],
            "overall_risk": overall,
        }

    @classmethod
    def _evidence_index(cls, c: dict[str, Any]) -> dict[str, Any]:
        """Every traceable number, grouped by symbol, for the evidence drawer."""
        index: dict[str, Any] = {}
        for symbol, analysis in c["technical_analysis"].items():
            records = list(analysis.get("evidence") or [])
            records += list((analysis.get("weekly_sma") or {}).get("evidence") or [])
            records += list(
                ((c["fundamental_analysis"].get(symbol) or {}).get("quality") or {}).get("evidence") or []
            )
            records += list(
                ((c["fundamental_analysis"].get(symbol) or {}).get("valuation_scenarios") or {}).get("evidence")
                or []
            )
            if records:
                index[symbol] = records
        return index

    @classmethod
    def _synthesis(cls, c: dict[str, Any]) -> dict[str, Any]:
        """Bull/Bear + audit + committee section; empty when not synthesized."""
        synthesis = c["research_synthesis"]
        if not isinstance(synthesis, dict) or not synthesis.get("per_symbol"):
            return {}
        per_symbol: dict[str, Any] = {}
        for symbol, entry in synthesis["per_symbol"].items():
            debate = entry.get("debate") or {}
            committee = entry.get("committee") or {}
            per_symbol[symbol] = {
                "thesis": debate.get("thesis"),
                "strongest_counter": debate.get("strongest_counter"),
                "invalidation": debate.get("invalidation"),
                "bull_points": debate.get("bull_points", []),
                "bear_points": debate.get("bear_points", []),
                "committee_verdict": committee.get("verdict"),
                "committee_conditions": committee.get("conditions", []),
                "position_cap_pct": committee.get("position_cap_pct"),
                "narrative": entry.get("narrative"),
                "analysts": entry.get("analysts"),
                "pm": entry.get("pm"),
            }
        return {
            "audit_verdict": (synthesis.get("audit") or {}).get("verdict"),
            "audit_stale": (synthesis.get("audit") or {}).get("stale", []),
            "audit_insufficient": (synthesis.get("audit") or {}).get("insufficient", []),
            "audit_conflicts": (synthesis.get("audit") or {}).get("conflicts", []),
            "by_symbol": per_symbol,
        }

    @classmethod
    def _recommendations(cls, c: dict[str, Any]) -> dict[str, Any]:
        if c["decisions"]:
            return cls._recommendations_from_decisions(c)
        return cls._recommendations_derived(c)

    @classmethod
    def _recommendations_from_decisions(cls, c: dict[str, Any]) -> dict[str, Any]:
        """Pipeline path: the decision agent already produced decisions."""
        summary: dict[str, Any] = {
            "by_symbol": {},
            "portfolio_actions": [],
            "top_pick": None,
            "avoid": [],
        }
        best_score = -float("inf")
        worst_score = float("inf")

        for symbol, decision in c["decisions"].items():
            action = decision.get("action", "hold")
            score = decision.get("score", 0)
            summary["by_symbol"][symbol] = {
                "action": action,
                "confidence": decision.get("confidence"),
                "position_size": (decision.get("position_size") or {}).get("percentage_of_portfolio"),
                "entry": (decision.get("price_targets") or {}).get("entry_zone"),
                "stop_loss": (decision.get("price_targets") or {}).get("stop_loss"),
                "take_profit": (decision.get("price_targets") or {}).get("take_profit"),
                "rationale": decision.get("rationale"),
            }
            if "buy" in str(action):
                summary["portfolio_actions"].append({"symbol": symbol, "action": action})
            elif "sell" in str(action):
                summary["avoid"].append(symbol)
            if isinstance(score, (int, float)) and score > best_score:
                best_score = score
                summary["top_pick"] = symbol
            if isinstance(score, (int, float)) and score < worst_score:
                worst_score = score
        return summary

    @classmethod
    def _recommendations_derived(cls, c: dict[str, Any]) -> dict[str, Any]:
        """ReAct path: derive the recommendation from the analysis sections."""
        by_symbol: dict[str, Any] = {}
        for symbol in c["symbols"]:
            fundamental = c["fundamental_analysis"].get(symbol) or {}
            technical = c["technical_analysis"].get(symbol) or {}
            sentiment = c["sentiment_flat"].get(symbol) or {}
            risk = c["risk_flat"].get(symbol) or {}

            if not any([fundamental, technical, sentiment, risk]):
                by_symbol[symbol] = {
                    "action": "hold",
                    "confidence": 0.3,
                    "composite_score": 50.0,
                    "reasoning": "Insufficient analysis data to derive a recommendation",
                }
                continue
            by_symbol[symbol] = derive_recommendation(
                symbol, fundamental, technical, sentiment, risk
            )

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

    # ------------------------------------------------------------------
    # Title & executive summary
    # ------------------------------------------------------------------

    @classmethod
    def build_title(cls, query: str, symbols: list[str]) -> str:
        if symbols:
            if len(symbols) == 1:
                return f"Investment Research Report: {symbols[0]}"
            return (
                f"Investment Research Report: {', '.join(symbols[:3])}"
                f"{'...' if len(symbols) > 3 else ''}"
            )
        return "Investment Research Report"

    @classmethod
    def executive_summary(cls, data: dict[str, Any], sections: dict[str, Any]) -> str:
        """Concise per-symbol summary; language matches the query."""
        c = cls._normalize(data)
        lang = detect_lang(c["query"])
        labels = _RECOMMEND_LABELS[lang]

        rec_section = sections.get("recommendations", {}) or {}
        by_symbol = rec_section.get("by_symbol", {}) or {}
        market_summary = (sections.get("overview", {}) or {}).get("market_summary", {}) or {}

        if not c["symbols"]:
            return "分析完成。" if lang == "zh" else "Analysis complete."

        parts: list[str] = []
        for symbol in c["symbols"]:
            rec = by_symbol.get(symbol, {}) or {}
            action = rec.get("action", "hold")
            confidence = rec.get("confidence", 0.5)
            composite = rec.get("composite_score")
            m = market_summary.get(symbol) or c["market_data"].get(symbol, {}) or {}
            price = m.get("current_price")
            company = m.get("company_name") or symbol

            price_str = f"${price:.2f}" if isinstance(price, (int, float)) else "N/A"
            composite_str = (
                f", {labels['composite']} {composite:.0f}/100"
                if composite is not None
                else ""
            )
            if lang == "zh":
                parts.append(
                    f"{company}({symbol}) 当前价 {price_str} — 建议: {labels[action]} "
                    f"(置信度 {confidence:.0%}{composite_str})。"
                )
            else:
                parts.append(
                    f"{company} ({symbol}) @ {price_str} — {labels['verdict']}: {labels[action]} "
                    f"(confidence {confidence:.0%}{composite_str})."
                )

        overall_risk = (sections.get("risk_analysis", {}) or {}).get("overall_risk", "medium")
        if lang == "zh":
            risk_label = _RISK_LABELS_ZH.get(overall_risk, overall_risk)
            parts.append(f"整体{labels['risk']}水平: {risk_label}。")
        else:
            parts.append(f"Overall {labels['risk']}: {overall_risk}.")

        return " ".join(parts)


_RISK_LABELS_ZH = {
    "very_low": "极低",
    "low": "低",
    "medium": "中",
    "high": "高",
    "very_high": "极高",
}

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


def detect_lang(text: str) -> str:
    """Return 'zh' if the text contains CJK characters, else 'en'."""
    if not text:
        return "en"
    for ch in text:
        if "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿":
            return "zh"
    return "en"


def _risk_to_score(risk_level: str) -> int:
    """Map risk level (low..very_high) to 0..100 (lower = safer)."""
    return {
        "very_low": 10, "low": 30, "medium": 50, "high": 75, "very_high": 95,
    }.get(str(risk_level).lower(), 50)


def derive_recommendation(
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
    # The per-symbol technical block is {"signals": {...}, "sentiment": {...}}.
    tech_trend = str(technical.get("signals", {}).get("trend", "neutral")).lower()
    tech_score = float(technical.get("sentiment", {}).get("score", 0) or 0)
    sent_score = float(sentiment.get("score", 0) or 0)
    risk_level = str(risk.get("risk_level", "medium")).lower()
    risk_penalty = _risk_to_score(risk_level)

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
