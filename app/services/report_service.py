"""ReportService — the single implementation of report section building.

Before V2 the pipeline (``app/agents/report_agent.py``) and the ReAct path
(``app/tools/report/generate.py``) each maintained their own section builders
over slightly different input shapes. Both now delegate here. The service
normalizes the two input shapes once, then builds the richest union of the
sections; LLMs only narrate, every number comes from the analysis data.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.analysis.events import next_earnings_window
from app.analysis.fundamental import compact_quality_view
from app.analysis.ic import STATIC_DIMENSION_WEIGHTS
from app.analysis.portfolio import suggest_weights
from app.analysis.technical import compact_weekly_view
from app.analysis.valuation import compact_valuation_view

# Bars of price history carried into the report for sparkline rendering.
# Three years of closes (~750 floats) would bloat every response; a sparkline
# only needs the recent tail.
SPARK_BARS = 90


def _price_spark(history: Any) -> list[float] | None:
    """Last ``SPARK_BARS`` daily closes, rounded — the minimal series a sparkline needs.

    Non-finite values (NaN holes from adjusted histories) are dropped rather
    than allowed into the JSON payload. Returns None when there is nothing to
    draw; callers leave the key absent (degraded convention).
    """
    closes = history.get("close") if isinstance(history, dict) else None
    if not isinstance(closes, list):
        return None
    spark = [
        round(float(value), 2)
        for value in closes[-SPARK_BARS:]
        if isinstance(value, int | float) and math.isfinite(value)
    ]
    return spark or None


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
        market_regime: dict[str, Any] | None = None
        if "risk_by_symbol" in risk:  # pipeline shape nests per-symbol data
            portfolio_risk = risk.get("portfolio_risk") or {}
            overall_risk_level = risk.get("overall_risk_level", "medium")
            market_regime = risk.get("market_regime")
            risk = risk.get("risk_by_symbol") or {}

        sentiment = data.get("sentiment_analysis") or {}
        overall_sentiment = sentiment.get("overall_sentiment", {})
        if "sentiment_by_symbol" in sentiment:
            sentiment = sentiment.get("sentiment_by_symbol") or {}

        # Gated decisions win: react_agent applies the risk committee's
        # veto/limit/watch to the NESTED data["decision"]["decisions"] map;
        # reading the top-level key first would bypass the gate and re-derive
        # a buy from the raw scores. Pipeline callers pass the same decisions
        # already unwrapped to the top level — same precedence as ic.py.
        decision_wrapper = data.get("decision")
        nested_decisions = (
            decision_wrapper.get("decisions") if isinstance(decision_wrapper, dict) else None
        )
        decisions = nested_decisions or data.get("decisions") or {}

        return {
            "query": data.get("query", ""),
            "symbols": symbols,
            "market_data": market,
            "financial_data": data.get("financial_data") or {},
            "technical_analysis": data.get("technical_analysis") or {},
            "fundamental_analysis": data.get("fundamental_analysis") or {},
            "sentiment_flat": sentiment,
            "overall_sentiment": overall_sentiment,
            "risk_flat": risk,
            "portfolio_risk": portfolio_risk,
            "market_regime": market_regime,
            "overall_risk_level": overall_risk_level,
            "decisions": decisions,
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
                "currency": mkt.get("currency"),
                "market_cap": mkt.get("market_cap"),
                "as_of": mkt.get("as_of"),
            }
            # Scheduled-uncertainty disclosure (annotation-only, same
            # convention as liquidity/sector_relative): the composite score
            # never reads it. Absent calendar → key omitted entirely.
            earnings = next_earnings_window(
                (c["financial_data"].get(symbol) or {}).get("earnings_dates")
            )
            if earnings:
                summary[symbol]["earnings"] = earnings
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
            entry = {
                "trend": signals.get("trend", "neutral"),
                "rsi": signals.get("rsi", "neutral"),
                "macd": signals.get("macd", "neutral"),
                "support": analysis.get("support", {}),
                "resistance": analysis.get("resistance", {}),
                "sentiment_score": score,
                "weekly_trend": compact_weekly_view(analysis.get("weekly_sma")),
            }
            # Stale feeds (suspension, broken source) must be visible in the
            # final report, not silently presented as current signals.
            freshness = analysis.get("freshness")
            if freshness:
                entry["freshness"] = freshness
            # Trend quality (Wilder ADX): direction alone can't tell a clean
            # stair from a range trading above its MAs. Absent on histories
            # too short to smooth two Wilder windows, like freshness above.
            adx = (analysis.get("indicators") or {}).get("adx")
            if adx is not None:
                entry["adx"] = adx
            if signals.get("trend_strength"):
                entry["trend_strength"] = signals["trend_strength"]
            spark = _price_spark(
                ((c.get("market_data") or {}).get(symbol) or {}).get("historical_data")
            )
            if spark:
                entry["price_spark"] = spark
            by_symbol[symbol] = entry
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
        numeric_scores: list[float] = []
        for symbol, analysis in c["fundamental_analysis"].items():
            overall = analysis.get("overall_score", {})
            if isinstance(overall, dict):
                score = overall.get("score")
                rating = overall.get("rating", "fair")
            else:  # legacy numeric score
                score = overall
                rating = "fair"
            # Insufficient data yields score=None — display it as such and
            # keep it OUT of the average instead of crashing on += None.
            if isinstance(score, int | float):
                numeric_scores.append(float(score))
            else:
                score = None
                rating = rating if rating != "fair" else "insufficient_data"
            by_symbol[symbol] = {
                "overall_score": score,
                "rating": rating,
                "recommendation": analysis.get("recommendation", "hold"),
                "profitability": analysis.get("profitability", {}).get("rating", "N/A"),
                "valuation": analysis.get("valuation", {}).get("rating", "N/A"),
                "financial_health": analysis.get("financial_health", {}).get("rating", "N/A"),
                "valuation_scenarios": compact_valuation_view(analysis.get("valuation_scenarios")),
                "quality": compact_quality_view(analysis.get("quality")),
            }

        overall_rating = "hold"
        if numeric_scores:
            avg = sum(numeric_scores) / len(numeric_scores)
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
            if isinstance(score, int | float):
                scores.append(score)
            by_symbol[symbol] = {
                "risk_level": analysis.get("risk_level", "medium"),
                "risk_score": score,
                "beta": metrics.get("beta"),
                "beta_ci_95_low": metrics.get("beta_ci_95_low"),
                "beta_ci_95_high": metrics.get("beta_ci_95_high"),
                "volatility": metrics.get("volatility_annualized"),
                "var_95": metrics.get("var_95"),
                "max_drawdown": metrics.get("max_drawdown"),
                "alpha_annualized": metrics.get("alpha_annualized"),
                "alpha_ci_95_low": metrics.get("alpha_ci_95_low"),
                "alpha_ci_95_high": metrics.get("alpha_ci_95_high"),
                "max_position_size": position.get("max_position_size"),
                "warnings": analysis.get("warnings", []),
            }
            # Annotation blocks pass through when present; degraded entries
            # stay lean — same convention as the technical section's
            # freshness key. The frontend risk card renders these, the
            # composite score never reads them.
            for key in ("liquidity", "sector_relative"):
                block = analysis.get(key)
                if isinstance(block, dict):
                    by_symbol[symbol][key] = block

        overall = c["overall_risk_level"]
        if c["overall_risk_level"] == "medium" and scores:
            avg = sum(scores) / len(scores)
            overall = "high" if avg >= 60 else "low" if avg < 30 else "medium"
        return {
            "by_symbol": by_symbol,
            "portfolio_risk": c["portfolio_risk"],
            "market_regime": c.get("market_regime"),
            "overall_risk": overall,
        }

    @classmethod
    def _evidence_index(cls, c: dict[str, Any]) -> dict[str, Any]:
        """Every traceable number, grouped by symbol, for the evidence drawer."""
        index: dict[str, Any] = {}
        for symbol in c["symbols"]:
            analysis = c["technical_analysis"].get(symbol) or {}
            records = list(analysis.get("evidence") or [])
            records += list((analysis.get("weekly_sma") or {}).get("evidence") or [])
            records += list(
                ((c["fundamental_analysis"].get(symbol) or {}).get("quality") or {}).get("evidence")
                or []
            )
            records += list(
                (
                    (c["fundamental_analysis"].get(symbol) or {}).get("valuation_scenarios") or {}
                ).get("evidence")
                or []
            )
            if not records:
                # Degraded symbols (e.g. thin AkShare A-share payloads with no
                # historical data) can lack analysis output entirely; surface
                # an explicit availability record so the drawer still covers
                # every requested symbol instead of dropping it silently.
                records = [
                    {
                        "source": "data_availability",
                        "note": "no analyzable market data; decision degraded",
                    }
                ]
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
        summary = (
            cls._recommendations_from_decisions(c)
            if c["decisions"]
            else cls._recommendations_derived(c)
        )
        # Allocation across the buy-worthy names — deterministic, additive;
        # None (fewer than two eligible) leaves the section unchanged.
        summary["suggested_weights"] = cls._suggested_weights(c, summary)
        return summary

    @staticmethod
    def _position_pct(decision: dict[str, Any]) -> float | None:
        """Position size in percent from either decision shape.

        Pipeline decisions nest it (``position_size.percentage_of_portfolio``);
        the ReAct gate writes a flat float (``position_size: 5.0`` meaning 5%).
        """
        position = decision.get("position_size")
        if isinstance(position, dict):
            position = position.get("percentage_of_portfolio")
        return position if isinstance(position, int | float) else None

    @staticmethod
    def _position_cap_pct(decision: dict[str, Any], risk: dict[str, Any]) -> float | None:
        """Tightest per-symbol cap the symbol's own recommendation obeys (%).

        The decision's sized position is already risk-capped upstream
        (``min(conviction_or_atr_size, risk.max_position_size)``); the risk
        engine's suggestion is consulted too so the derived path (which has
        no decision sizes) stays bounded. Both are percent units.
        """
        cap_candidates: list[float] = []
        position = ReportService._position_pct(decision)
        if position is not None and position > 0:
            cap_candidates.append(float(position))
        max_from_risk = (risk.get("position_recommendation") or {}).get("max_position_size")
        if isinstance(max_from_risk, int | float) and max_from_risk > 0:
            cap_candidates.append(float(max_from_risk))
        return min(cap_candidates) if cap_candidates else None

    @staticmethod
    def _suggested_weights(c: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any] | None:
        """Candidates for the portfolio allocation from either path.

        Conviction comes from the decision agent (pipeline) or the derived
        recommendation (ReAct); volatility from the shared risk metrics.
        Only symbols whose action says buy participate — a sell/hold name
        gets no allocation, and the caller needs no action filtering. Each
        candidate also carries its own position cap (percent, converted to
        a fraction here) so the allocator can never hand a risk-limited
        name the uniform default weight its own recommendation forbids.
        """
        candidates: dict[str, dict[str, float | None]] = {}
        caps: dict[str, float] = {}
        for symbol in c["symbols"]:
            decision = c["decisions"].get(symbol) or summary["by_symbol"].get(symbol) or {}
            action = str(decision.get("action", ""))
            if "buy" not in action and action != "add":
                continue
            risk = c["risk_flat"].get(symbol) or {}
            metrics = risk.get("metrics") or {}
            candidates[symbol] = {
                "conviction": decision.get("confidence"),
                "volatility_annualized": metrics.get("volatility_annualized"),
            }
            cap_pct = ReportService._position_cap_pct(decision, risk)
            if cap_pct is not None:
                caps[symbol] = cap_pct / 100.0
        return suggest_weights(candidates, caps=caps or None)

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
                "position_size": cls._position_pct(decision),
                "entry": (decision.get("price_targets") or {}).get("entry_zone"),
                "stop_loss": (decision.get("price_targets") or {}).get("stop_loss"),
                "take_profit": (decision.get("price_targets") or {}).get("take_profit"),
                "rationale": decision.get("rationale"),
            }
            if "buy" in str(action):
                summary["portfolio_actions"].append({"symbol": symbol, "action": action})
            elif "sell" in str(action):
                summary["avoid"].append(symbol)
            if isinstance(score, int | float) and score > best_score:
                best_score = score
                summary["top_pick"] = symbol
            if isinstance(score, int | float) and score < worst_score:
                worst_score = score
        return summary

    @classmethod
    def _recommendations_derived(cls, c: dict[str, Any]) -> dict[str, Any]:
        """ReAct path: derive the recommendation from the analysis sections."""
        # Same weights the pipeline decision path consults — the snapshot it
        # primed, when warm; a cold process blends static. Keeps the two
        # paths on one formula, the whole point of sharing derive_recommendation.
        from app.services.ic_service import peek_dimension_weights

        snapshot = peek_dimension_weights()
        dimension_weights = snapshot[0] if snapshot is not None else None
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
                symbol,
                fundamental,
                technical,
                sentiment,
                risk,
                dimension_weights=dimension_weights,
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

            # No price AND no usable technical block means the data layer
            # failed for this symbol — say so loudly instead of dressing a
            # neutral fallback up as a real "hold" recommendation.
            tech_block = c["technical_analysis"].get(symbol)
            tech_usable = isinstance(tech_block, dict) and tech_block and "_error" not in tech_block
            if price is None and not tech_usable:
                if lang == "zh":
                    parts.append(
                        f"⚠ {symbol}: 行情数据不可用,本次未能生成有效分析(以下为空数据回退,不构成建议)。"
                    )
                else:
                    parts.append(
                        f"⚠ {symbol}: market data unavailable — no valid analysis was produced "
                        f"(sections below are empty-data fallbacks, not advice)."
                    )
                continue

            price_str = f"${price:.2f}" if isinstance(price, int | float) else "N/A"
            composite_str = (
                f", {labels['composite']} {composite:.0f}/100" if composite is not None else ""
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
        "buy": "BUY",
        "add": "ADD",
        "hold": "HOLD",
        "reduce": "REDUCE",
        "sell": "SELL",
        "verdict": "Recommendation",
        "composite": "composite score",
        "based_on": "based on",
        "fund": "fundamental",
        "tech": "technical",
        "sent": "sentiment",
        "risk": "risk",
    },
    "zh": {
        "buy": "买入",
        "add": "加仓",
        "hold": "持有",
        "reduce": "减仓",
        "sell": "卖出",
        "verdict": "投资建议",
        "composite": "综合评分",
        "based_on": "基于",
        "fund": "基本面",
        "tech": "技术面",
        "sent": "情绪",
        "risk": "风险",
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
        "very_low": 10,
        "low": 30,
        "medium": 50,
        "high": 75,
        "very_high": 95,
    }.get(str(risk_level).lower(), 50)


# Signals computed on stale bars (suspension, broken feed) cannot support
# full conviction. The composite still reflects the bars' own date; the
# cap makes the recommendation say "dated view", and pushes confidence
# below the low-confidence warning threshold.
STALE_CONFIDENCE_CAP = 0.4


def derive_recommendation(
    symbol: str,
    fundamental: dict,
    technical: dict,
    sentiment: dict,
    risk: dict,
    dimension_weights: Mapping[str, float] | None = None,
) -> dict:
    """Rule-based action synthesis that ALWAYS agrees with the analysis.

    Combines fundamental score (0-100), technical sentiment (-100..100),
    sentiment score (-100..100), and risk level into a single action.
    The LLM cannot override this — guarantees the report is internally
    consistent (e.g. fundamental=strong_sell ⇒ action=sell, not "add").

    Availability-aware: each dimension votes only with the evidence it
    actually has — weights renormalize over the available dimensions (the
    same available_weight pattern the fundamental scorer uses internally).
    A CN name without financials used to collect a neutral-50 fundamental
    vote worth 22.5 points on zero evidence; now its action rides the
    dimensions that measured something. Full-data composites are
    bit-identical (all four present → the classic 45/30/15/10 blend).

    ``dimension_weights`` overrides the directional blend (fundamental/
    technical/sentiment) — the IC-adaptive weights pathway. Unknown keys
    are ignored and missing keys fall back to the static constants, so a
    partial dict can never silently zero a dimension.
    """
    fund_raw = fundamental.get("overall_score")
    if isinstance(fund_raw, dict):
        fund_raw = fund_raw.get("score")
    fund_score = float(fund_raw) if isinstance(fund_raw, int | float) else None
    fund_rec = str(fundamental.get("recommendation", "hold")).lower()
    # The per-symbol technical block is {"signals": {...}, "sentiment": {...}}.
    tech_trend = str(technical.get("signals", {}).get("trend", "neutral")).lower()
    tech_raw = technical.get("sentiment", {}).get("score")
    tech_score = float(tech_raw) if isinstance(tech_raw, int | float) else None
    sent_raw = sentiment.get("score")
    # A zero-article feed scored 0 is absence, not neutrality.
    sent_score = (
        float(sent_raw)
        if isinstance(sent_raw, int | float) and (sentiment.get("article_count") or 0) > 0
        else None
    )
    risk_level = str(risk.get("risk_level") or "").lower()
    risk_available = bool(risk_level) and risk_level != "insufficient_data"

    # Directional blend: caller-provided IC-adaptive weights or the static
    # 45/30/15 constants. Partial dicts fall back per-key, never silently
    # zeroing a dimension. Risk's 0.10 modifier weight is fixed — risk is a
    # modifier, not a signal, and no IC is measured for it.
    weights = {
        **STATIC_DIMENSION_WEIGHTS,
        **{
            k: float(v)
            for k, v in (dimension_weights or {}).items()
            if k in STATIC_DIMENSION_WEIGHTS
        },
    }

    parts: list[tuple[float, float]] = []  # (normalized score, weight)
    missing: list[str] = []
    if fund_score is not None:
        parts.append((fund_score, weights["fundamental"]))
    else:
        missing.append("fundamental")
    if tech_score is not None:
        parts.append((max(0.0, min(100.0, (tech_score + 100) / 2)), weights["technical"]))
    else:
        missing.append("technical")
    if sent_score is not None:
        parts.append((max(0.0, min(100.0, (sent_score + 100) / 2)), weights["sentiment"]))
    else:
        missing.append("sentiment")
    if risk_available:
        parts.append((100.0 - _risk_to_score(risk_level), 0.10))  # higher = safer
    else:
        missing.append("risk")

    if fund_score is None and tech_score is None and sent_score is None:
        # No directional dimension has data. Risk is a modifier, never a
        # signal: "low risk" alone must not become a buy, so the decision
        # holds at zero conviction.
        return {
            "action": "hold",
            "confidence": 0.0,
            "composite_score": None,
            "reasoning": (
                "Only risk data available — risk alone cannot recommend; "
                "holding with zero conviction"
                if risk_available
                else "No dimension has data to score; holding with zero conviction"
            ),
        }

    combined = sum(score * weight for score, weight in parts) / sum(weight for _, weight in parts)

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

    evidence_bits = [f"fundamental {fund_score:.0f}/{fund_rec}"] if fund_score is not None else []
    if tech_score is not None:
        evidence_bits.append(f"technical {tech_trend}/{tech_score:+.0f}")
    if sent_score is not None:
        evidence_bits.append(f"sentiment {sent_score:+.0f}")
    if risk_available:
        evidence_bits.append(f"risk {risk_level}")
    reasoning = f"Composite score {combined:.0f}/100 ({', '.join(evidence_bits)})"
    if missing:
        reasoning += f" [{', '.join(missing)} unavailable — weights renormalized]"

    # Stale price data caps conviction at both seams' shared formula so the
    # pipeline decision agent and the ReAct report path stay in agreement.
    # Fresh or absent freshness leaves confidence untouched.
    freshness = technical.get("freshness") or {}
    if freshness.get("stale"):
        confidence = min(confidence, STALE_CONFIDENCE_CAP)
        reasoning += f"; price data stale as of {freshness.get('as_of', 'unknown date')}"

    return {
        "action": action,
        "confidence": confidence,
        "composite_score": round(combined, 1),
        "reasoning": reasoning,
    }
