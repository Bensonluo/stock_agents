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

from app.analysis.events import build_catalysts_view, next_earnings_window
from app.analysis.fundamental import compact_quality_view
from app.analysis.ic import STATIC_DIMENSION_WEIGHTS
from app.analysis.portfolio import suggest_weights
from app.analysis.regime import decision_warnings, option_regime_warnings, regime_warnings
from app.analysis.risk import risk_evidence
from app.analysis.technical import compact_weekly_view
from app.analysis.valuation import compact_valuation_view

# Bars of price history carried into the report for sparkline rendering.
# Three years of closes (~750 floats) would bloat every response; a sparkline
# only needs the recent tail.
SPARK_BARS = 90

# Cap for long free-text fields (business summary, LLM news verdict) riding
# the report payload — the wire carries the gist, the full text lives
# upstream in the analysis data.
TEXT_CAP_CHARS = 200


def _cap_text(text: Any) -> str | None:
    """Free text truncated to ``TEXT_CAP_CHARS``; None when absent."""
    if not isinstance(text, str) or not text:
        return None
    return text[:TEXT_CAP_CHARS]


def _as_of_datetime(value: Any) -> datetime | None:
    """market_data's ``as_of`` (ISO date/datetime string) as a datetime.

    risk_evidence's evidence records need a datetime cutoff — its date
    parsing path feeds ``date`` objects into ``make_evidence``, which calls
    ``.date()`` on them. None when nothing parseable is given.
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


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
        catalysts = cls._catalysts(c)
        if catalysts:
            sections["catalysts"] = catalysts
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
        option_implied: dict[str, Any] | None = None
        if "risk_by_symbol" in risk:  # pipeline shape nests per-symbol data
            portfolio_risk = risk.get("portfolio_risk") or {}
            overall_risk_level = risk.get("overall_risk_level", "medium")
            market_regime = risk.get("market_regime")
            option_implied = risk.get("option_implied")
            risk = risk.get("risk_by_symbol") or {}
        else:
            # ReAct shape: assess_risk parks the run-level regime under a
            # namespaced key beside the per-symbol entries — lift it out so
            # the flat map stays purely per-symbol (position sizing reads it).
            market_regime = risk.get("market_regime")
            if market_regime is not None:
                risk = {k: v for k, v in risk.items() if k != "market_regime"}
            option_implied = risk.get("option_implied")
            if option_implied is not None:
                risk = {k: v for k, v in risk.items() if k != "option_implied"}

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

        # ReAct's analyze_valuation parks its per-symbol scenario results in a
        # top-level data["valuation_analysis"] map that this normalizer used to
        # ignore — ReAct reports shipped without valuation scenarios. Route
        # each result into the fundamental entry under the pipeline's
        # valuation_scenarios key (same shape: the full engine result that
        # compact_valuation_view reads). Entries are copied, never mutated in
        # place — _normalize runs more than once per report on the same data.
        fundamental = data.get("fundamental_analysis") or {}
        valuation_bucket = data.get("valuation_analysis")
        if isinstance(valuation_bucket, dict) and valuation_bucket:
            fundamental = dict(fundamental)
            for symbol in symbols:
                result = valuation_bucket.get(symbol)
                if not isinstance(result, dict):
                    continue
                entry = fundamental.get(symbol)
                entry = dict(entry) if isinstance(entry, dict) else {}
                if not entry.get("valuation_scenarios"):
                    entry["valuation_scenarios"] = result
                fundamental[symbol] = entry

        return {
            "query": data.get("query", ""),
            "symbols": symbols,
            "market_data": market,
            "financial_data": data.get("financial_data") or {},
            "technical_analysis": data.get("technical_analysis") or {},
            "fundamental_analysis": fundamental,
            "sentiment_flat": sentiment,
            "overall_sentiment": overall_sentiment,
            "risk_flat": risk,
            "portfolio_risk": portfolio_risk,
            "market_regime": market_regime,
            "option_implied": option_implied,
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
                # Snapshot depth the data agent already mapped (52-week band,
                # average volume, prior close, industry, business summary) but
                # the overview discarded — same pure passthrough as above.
                "previous_close": mkt.get("previous_close"),
                "avg_volume": mkt.get("avg_volume"),
                "52_week_high": mkt.get("52_week_high"),
                "52_week_low": mkt.get("52_week_low"),
                "industry": mkt.get("industry"),
                "description": _cap_text(mkt.get("description")),
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
            # Degraded entries (no bars / insufficient history) must not read
            # as a real neutral verdict on the wire — the frontend renders an
            # outage line for them. Healthy entries omit the key (the same
            # optional-key convention as freshness and the sparkline).
            if analysis.get("status", "available") != "available" or not signals:
                entry["status"] = analysis.get("status") or "unavailable"
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
            # Depth passthrough: the scorer computed a numeric score and the
            # raw metric values behind every dimension rating; dropping them
            # made each rating un-auditable on the wire. Optional-key
            # convention: absent or insufficient_data dimensions add no keys
            # (the scorer's insufficient path reports a hardcoded score 0 —
            # absence, not a real zero).
            for dim in ("profitability", "valuation", "financial_health"):
                block = analysis.get(dim)
                if not isinstance(block, dict) or block.get("status") == "insufficient_data":
                    continue
                dim_score = block.get("score")
                if isinstance(dim_score, int | float):
                    by_symbol[symbol][f"{dim}_score"] = dim_score
                details = block.get("details")
                if isinstance(details, dict) and details:
                    by_symbol[symbol][f"{dim}_details"] = details
            growth = analysis.get("growth")
            if (
                isinstance(growth, dict)
                and growth.get("status") != "insufficient_data"
                and growth.get("score") is not None
            ):
                by_symbol[symbol]["growth"] = {
                    "score": growth.get("score"),
                    "rating": growth.get("rating"),
                    "details": growth.get("details") or {},
                }
            # CN analyst consensus rides the raw financial_data map (the data
            # agent attaches it there per symbol); the fundamental score never
            # reads it — the same annotation-only passthrough as the risk
            # section's liquidity/sector_relative blocks. Absent → key omitted.
            consensus = (c["financial_data"].get(symbol) or {}).get("consensus")
            if isinstance(consensus, dict):
                by_symbol[symbol]["consensus"] = consensus

        overall_rating = "hold"
        if numeric_scores:
            avg = sum(numeric_scores) / len(numeric_scores)
            overall_rating = "buy" if avg >= 65 else "sell" if avg < 35 else "hold"
        return {"by_symbol": by_symbol, "overall_rating": overall_rating}

    @classmethod
    def _sentiment(cls, c: dict[str, Any]) -> dict[str, Any]:
        by_symbol: dict[str, Any] = {}
        for symbol, analysis in c["sentiment_flat"].items():
            entry: dict[str, Any] = {
                "sentiment": analysis.get("sentiment", "neutral"),
                "score": analysis.get("score", 0),
                "trend": analysis.get("trend", "stable"),
                "article_count": analysis.get("article_count", 0),
            }
            # Per-article scores and the LLM verdict are computed upstream then
            # dropped; both are cheap to carry and render on the card. Empty
            # score lists add nothing, and the LLM summary rides only when
            # short (capped like the overview business summary) — the full
            # text stays upstream.
            recent_scores = analysis.get("recent_scores")
            if isinstance(recent_scores, list) and recent_scores:
                entry["recent_scores"] = recent_scores
            llm = analysis.get("llm_analysis")
            if isinstance(llm, dict) and llm:
                compact: dict[str, Any] = {}
                for key in ("overall_sentiment", "confidence"):
                    if llm.get(key) is not None:
                        compact[key] = llm[key]
                summary = _cap_text(llm.get("summary"))
                if summary:
                    compact["summary"] = summary
                if compact:
                    entry["llm_analysis"] = compact
            by_symbol[symbol] = entry
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
            # Deep tail/relative metrics the engine computed but the card
            # dropped. Only present when actually measured — degraded
            # entries stay lean (same convention as the blocks above).
            for key in (
                "var_99",
                "cvar_95",
                "sortino",
                "downside_risk",
                "volatility_percentile_20d",
                "r_squared",
                "correlation",
            ):
                value = metrics.get(key)
                if isinstance(value, int | float):
                    by_symbol[symbol][key] = value
            # Beta-scaled market-shock impacts: compact scenario→implied
            # move map. Without beta the engine honestly reports
            # insufficient_data — nothing to fabricate, key omitted.
            stress = analysis.get("stress_scenarios")
            if isinstance(stress, dict):
                scenarios = stress.get("scenarios")
                if isinstance(scenarios, dict) and scenarios:
                    by_symbol[symbol]["stress_scenarios"] = scenarios

        overall = c["overall_risk_level"]
        if c["overall_risk_level"] == "medium" and scores:
            avg = sum(scores) / len(scores)
            overall = "high" if avg >= 60 else "low" if avg < 30 else "medium"
        risk_section = {
            "by_symbol": by_symbol,
            "portfolio_risk": c["portfolio_risk"],
            "market_regime": c.get("market_regime"),
            "overall_risk": overall,
        }
        # Market-level option annotation rides the run-level risk section by
        # presence — same convention as the per-symbol annotation blocks; the
        # composite score never reads it.
        option_implied = c.get("option_implied")
        if isinstance(option_implied, dict):
            risk_section["option_implied"] = option_implied
        return risk_section

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
            # The risk engine's evidence generator (exported but previously
            # uncalled) pins the headline risk numbers to their formulas.
            # market_data's as_of is the cutoff those metrics were computed
            # at; with no usable cutoff the generator returns nothing by
            # itself. Metrics are filtered to finite numerics so a malformed
            # block can never raise inside the report build.
            risk_metrics = (c["risk_flat"].get(symbol) or {}).get("metrics")
            if isinstance(risk_metrics, dict) and risk_metrics:
                numeric = {
                    key: value
                    for key, value in risk_metrics.items()
                    if isinstance(value, int | float) and math.isfinite(value)
                }
                if numeric:
                    records += [
                        item.model_dump(mode="json")
                        for item in risk_evidence(
                            symbol=symbol,
                            metrics=numeric,
                            as_of=_as_of_datetime(
                                (c["market_data"].get(symbol) or {}).get("as_of")
                            ),
                        )
                    ]
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
    def _catalysts(cls, c: dict[str, Any]) -> dict[str, Any]:
        """Upcoming events + recent EPS surprise per symbol; empty → absent.

        The data layer's ``event_calendar``/``earnings_surprise`` blocks ride
        ``financial_data``; the view buckets them 1w/1m/3m for the timeline
        card. A symbol with neither an upcoming event nor a surprise row is
        omitted entirely (optional-key convention) so old/thin payloads never
        render an empty shell section.
        """
        by_symbol: dict[str, Any] = {}
        financial_all = c.get("financial_data") or {}
        for symbol in c["symbols"]:
            financial = financial_all.get(symbol) or {}
            view = build_catalysts_view(
                symbol,
                financial.get("event_calendar"),
                financial.get("earnings_surprise"),
            )
            if view["events"] or view["earnings_surprise"]:
                by_symbol[symbol] = view
        return {"by_symbol": by_symbol} if by_symbol else {}

    # 决策期限结构: 窗口(天)与各窗口的主导分析层 — 固定映射、显式声明。
    # 短期由价格动量与消息情绪主导, 中期叠加基本面, 三个月窗口基本面与风险
    # 接管。这不是给每个期限另编一套动作(会与唯一决策自相矛盾), 而是解释
    # 同一个决策在不同期限下的依据结构、窗口内事件与观察点。
    HORIZON_WINDOWS = {"1w": 7, "1m": 31, "3m": 92}
    HORIZON_DRIVERS = {
        "1w": ("technical", "sentiment"),
        "1m": ("technical", "fundamental", "sentiment"),
        "3m": ("fundamental", "risk"),
    }

    @classmethod
    def _horizon_views(cls, c: dict[str, Any]) -> dict[str, Any]:
        """Per-horizon term structure of the single decision, per symbol.

        Each window states which analysis layers dominate it, the nearest
        catalyst landing inside it (from the catalysts view), and what to
        watch (deterministic template lines from measured data — weekly
        alignment, valuation spread, invalidation). A symbol whose windows
        carry no catalyst and no watch line is omitted: three constant
        driver lists are not detail.
        """
        catalysts = cls._catalysts(c).get("by_symbol") or {}
        synthesis = (c.get("research_synthesis") or {}).get("per_symbol") or {}
        out: dict[str, Any] = {}
        for symbol in c["symbols"]:
            events = (catalysts.get(symbol) or {}).get("events") or []
            debate = (synthesis.get(symbol) or {}).get("debate") or {}
            invalidation = debate.get("invalidation")
            horizons: dict[str, Any] = {}
            has_content = False
            window_floor = 0.0
            for horizon, window in cls.HORIZON_WINDOWS.items():
                entry: dict[str, Any] = {"drivers": list(cls.HORIZON_DRIVERS[horizon])}
                # Tiered reveal: each horizon shows the nearest catalyst that
                # ENTERS view at this tier — (prev window, this window]. The
                # 1w/1m/3m cards then read as progressive detail, not three
                # copies of the same nearest event.
                window_events = [
                    e
                    for e in events
                    if isinstance(e.get("days_until"), int | float)
                    and window_floor < e["days_until"] <= window
                ]
                if window_events:
                    nearest = window_events[0]
                    entry["catalyst"] = {
                        "date": nearest.get("date"),
                        "type": nearest.get("type"),
                        "title": nearest.get("title"),
                        "days_until": nearest.get("days_until"),
                    }
                    has_content = True
                watch = cls._horizon_watch(c, symbol, horizon, invalidation)
                if watch:
                    entry["watch"] = watch
                    has_content = True
                horizons[horizon] = entry
                window_floor = window
            if has_content:
                out[symbol] = horizons
        return out

    @staticmethod
    def _horizon_watch(
        c: dict[str, Any], symbol: str, horizon: str, invalidation: Any
    ) -> list[str] | None:
        """Deterministic per-horizon watch lines from measured data only."""
        watch: list[str] = []
        technical = (c.get("technical_analysis") or {}).get(symbol) or {}
        fundamental = (c.get("fundamental_analysis") or {}).get(symbol) or {}
        if horizon in ("1w", "1m"):
            weekly = compact_weekly_view(technical.get("weekly_sma"))
            if weekly.get("status") not in (None, "unavailable", "insufficient_data"):
                alignment = weekly.get("alignment") or {}
                state = alignment.get("state")
                weeks = alignment.get("weeks_in_state")
                if state and state != "unknown":
                    line = f"周线排列{state}"
                    if isinstance(weeks, int | float):
                        line += f"(持续{int(weeks)}周)"
                    watch.append(line)
                crosses = weekly.get("recent_crosses") or {}
                for pair, cross in crosses.items():
                    direction = str(cross.get("direction") or "")
                    label = {"golden": "金叉", "death": "死叉"}.get(direction, direction)
                    if not label:
                        continue
                    line = f"{pair} {label}"
                    since = cross.get("weeks_since")
                    if isinstance(since, int | float):
                        line += f"({int(since)}周前)"
                    watch.append(line)
                    break
        if horizon == "1m":
            scenarios = (compact_valuation_view(fundamental.get("valuation_scenarios")) or {}).get(
                "scenarios"
            ) or {}
            upsides = [
                item.get("upside_pct")
                for method in scenarios.values()
                for item in (method or {}).values()
                if isinstance(item, dict)
            ]
            upsides = [u for u in upsides if isinstance(u, int | float)]
            if upsides:
                watch.append(f"情景区间 {min(upsides):+.0f}% ~ {max(upsides):+.0f}%")
        if horizon == "3m":
            quality = compact_quality_view(fundamental.get("quality")) or {}
            red_flags = quality.get("red_flags")
            if isinstance(red_flags, list) and red_flags:
                watch.append(f"财务质量红旗{len(red_flags)}项")
            if isinstance(invalidation, str) and invalidation.strip():
                watch.append(f"失效条件: {invalidation.strip()}")
        return watch or None

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
        # Term structure of the single decision: per-horizon drivers, window
        # catalysts and watch lines. Absent when nothing measured (the
        # optional-key convention — three constant driver lists are noise).
        horizons = cls._horizon_views(c)
        if horizons:
            summary["horizons"] = horizons
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
            # Decision warnings (low-confidence notices, regime-conditional
            # buyer-risk warnings) are user-facing risk flags — the
            # recommendation card renders them. Warning-free decisions omit
            # the key (optional-key convention).
            warnings = decision.get("warnings")
            if warnings:
                summary["by_symbol"][symbol]["warnings"] = warnings
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
                rec = {
                    "action": "hold",
                    "confidence": 0.3,
                    "composite_score": 50.0,
                    "reasoning": "Insufficient analysis data to derive a recommendation",
                }
            else:
                rec = derive_recommendation(
                    symbol,
                    fundamental,
                    technical,
                    sentiment,
                    risk,
                    dimension_weights=dimension_weights,
                )
            # Same decision-layer warnings the pipeline decision agent emits
            # (shared generators in app/analysis/regime.py) so both paths
            # speak with one voice. Warning-free recs omit the key.
            warnings = (
                decision_warnings(rec["action"], risk, rec.get("confidence") or 0)
                + regime_warnings(rec["action"], c["market_regime"])
                + option_regime_warnings(rec["action"], c.get("option_implied"))
            )
            if warnings:
                rec["warnings"] = warnings
            by_symbol[symbol] = rec

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

    Renormalization stops at the market-data gate: a symbol whose only
    price-data dimension (technical) is unusable — block absent/empty, a
    failed-fetch ``_error`` block, or the pipeline's ``insufficient_data``
    block whose hardcoded zero score is absence, not neutrality — gets no
    directional call at all. Hold at zero conviction with the surviving
    evidence recorded in the reasoning; news sentiment renormalized to
    full weight must never masquerade as a directional view. Stale-but-
    present bars are data, not absence, and are not gated (dated view,
    confidence capped below).

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

    # Market-data gate (2026-09-27 production smoke): with every quotes
    # feed down, symbols still shipped directional calls — news sentiment,
    # renormalized to full weight over the missing technical dimension,
    # published "sell" at 0.85 on zero price data. No usable technical
    # dimension means no direction to judge: withhold the call, hold at
    # zero conviction, keep the surviving evidence visible. Unusable is
    # either no numeric technical score (block absent/empty/_error) or
    # the pipeline's insufficient_data block, whose hardcoded score 0 is
    # absence dressed as a neutral vote. Stale-but-present bars carry a
    # real score and never hit this gate — iteration 23 semantics (the
    # view stands, confidence capped) apply unchanged below.
    if tech_score is None or technical.get("status") == "insufficient_data":
        survivors = []
        if fund_score is not None:
            survivors.append(f"fundamental {fund_score:.0f}/{fund_rec}")
        if sent_score is not None:
            survivors.append(f"sentiment {sent_score:+.0f}")
        if risk_available:
            survivors.append(f"risk {risk_level}")
        return {
            "action": "hold",
            "confidence": 0.0,
            "composite_score": None,
            "reasoning": (
                "Market data unavailable — technical analysis has nothing to "
                "score; directional action withheld, holding with zero "
                f"conviction (surviving evidence: {', '.join(survivors)})"
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
