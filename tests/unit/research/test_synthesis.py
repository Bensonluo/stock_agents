"""Specification tests for the research synthesis layer (V2 plan §6)."""

from __future__ import annotations

from datetime import date, timedelta

from app.research import audit_packets, bull_bear_debate, committee_review, synthesize


def _technical(*, trend: str = "bullish", score: int = 40, alignment: str = "bullish") -> dict:
    return {
        "status": "available",
        "signals": {"trend": trend},
        "sentiment": {"score": score},
        "weekly_sma": {"alignment": {"state": alignment, "weeks_in_state": 12}},
    }


def _fundamental(*, red_flags: list | None = None, cagr: float | None = 0.15) -> dict:
    quality: dict = {"status": "available", "red_flags": red_flags or []}
    if cagr is not None:
        quality["revenue_trend"] = {"cagr": cagr}
    return {
        "overall_score": {"score": 70},
        "quality": quality,
        "valuation_scenarios": {"status": "available", "methods": {}},
    }


class TestBullBearDebate:
    def test_strong_uptrend_produces_bull_points_and_thesis(self) -> None:
        packet = {"technical_analysis": _technical()}
        debate = bull_bear_debate("AAPL", packet)

        assert debate["bull_points"]
        assert debate["thesis"] is not None
        assert all("evidence_ref" in point for point in debate["bull_points"])
        assert debate["bear_points"] == []  # uptrend with clean fundamentals

    def test_critical_red_flag_dominates_invalidation(self) -> None:
        packet = {
            "technical_analysis": _technical(),
            "fundamental_analysis": _fundamental(
                red_flags=[
                    {
                        "code": "negative_cfo_positive_ni",
                        "severity": "critical",
                        "detail": "Profit without cash.",
                    }
                ]
            ),
        }
        debate = bull_bear_debate("FAKE", packet)

        assert debate["invalidation"] == "Red flag: Profit without cash."
        assert any(point["severity"] == "critical" for point in debate["bear_points"])

    def test_empty_packet_yields_no_direction(self) -> None:
        debate = bull_bear_debate("EMPTY", {})

        assert debate["bull_points"] == []
        assert debate["bear_points"] == []
        assert debate["thesis"] is None
        assert debate["invalidation"] is None


class TestEvidenceAuditor:
    def test_fresh_complete_data_passes(self) -> None:
        data = {
            "market_data": {"AAPL": {"as_of": date.today().isoformat(), "current_price": 100.0}},
            "technical_analysis": {"AAPL": _technical()},
            "fundamental_analysis": {"AAPL": _fundamental()},
            "risk_assessment": {"AAPL": {"risk_level": "medium", "metrics": {}}},
        }

        audit = audit_packets(data)

        assert audit["verdict"] == "pass"
        assert audit["stale"] == []

    def test_fetch_failure_skeleton_does_not_audit_clean(self) -> None:
        """The hollow-report shape the ReAct path produces when every data
        source fails: market block without price/as_of, sections keyed
        '_error'. The audit must say so, not 'pass'."""
        data = {
            "market_data": {"AAPL": {"company_name": None, "current_price": None, "as_of": None}},
            "technical_analysis": {"_error": {"error": "Could not fetch data for AAPL"}},
            "fundamental_analysis": {"_error": {"error": "Could not fetch data for AAPL"}},
            "risk_assessment": {"_error": {"error": "Could not fetch data for AAPL"}},
        }

        audit = audit_packets(data)

        assert audit["verdict"] == "warnings"
        subjects = {finding["subject"] for finding in audit["insufficient"]}
        assert "market_data" in subjects
        assert "technical_analysis" in subjects
        assert "risk_assessment" in subjects

    def test_total_data_failure_without_market_key_is_flagged(self) -> None:
        """Live-run shape: when EVERY provider fails the ReAct path omits
        market_data entirely — the audit must still cover the symbol."""
        data = {
            "symbols": ["AAPL"],
            "technical_analysis": {"_error": {"error": "Could not fetch data for AAPL"}},
            "fundamental_analysis": {"_error": {"error": "Could not fetch data for AAPL"}},
            "risk_assessment": {"_error": {"error": "Could not fetch data for AAPL"}},
        }

        audit = audit_packets(data)

        assert audit["verdict"] == "warnings"
        subjects = {finding["subject"] for finding in audit["insufficient"]}
        assert "market_data" in subjects
        assert "technical_analysis" in subjects

    def test_stale_market_data_blocks(self) -> None:
        data = {"market_data": {"AAPL": {"as_of": (date.today() - timedelta(days=30)).isoformat()}}}

        audit = audit_packets(data)

        assert audit["verdict"] == "blocked"
        assert audit["stale"][0]["symbol"] == "AAPL"

    def test_critical_conflict_between_flags_and_momentum(self) -> None:
        data = {
            "market_data": {"FAKE": {"as_of": date.today().isoformat()}},
            "technical_analysis": {"FAKE": _technical(score=50)},
            "fundamental_analysis": {
                "FAKE": _fundamental(
                    red_flags=[
                        {
                            "code": "negative_equity",
                            "severity": "critical",
                            "detail": "Negative equity.",
                        }
                    ]
                )
            },
            "sentiment_analysis": {"FAKE": {"score": 50}},
        }

        audit = audit_packets(data)

        assert audit["verdict"] == "blocked"
        assert audit["conflicts"][0]["severity"] == "critical"

    def test_insufficient_blocks_are_listed_not_hidden(self) -> None:
        data = {
            "market_data": {"NEW": {"as_of": date.today().isoformat()}},
            "fundamental_analysis": {"NEW": {"quality": {"status": "insufficient_data"}}},
        }

        audit = audit_packets(data)

        assert any(f["subject"] == "fundamental_analysis.quality" for f in audit["insufficient"])
        assert audit["verdict"] == "warnings"


class TestRiskCommittee:
    def test_blocked_audit_vetoes(self) -> None:
        decision = committee_review("X", risk=None, quality=None, audit_verdict="blocked")

        assert decision["verdict"] == "veto"

    def test_critical_red_flag_vetoes_even_with_low_risk(self) -> None:
        decision = committee_review(
            "X",
            risk={"risk_level": "low", "metrics": {}},
            quality={"red_flags": [{"severity": "critical", "code": "negative_equity"}]},
            audit_verdict="pass",
        )

        assert decision["verdict"] == "veto"

    def test_high_risk_limits_with_conditions_not_direction(self) -> None:
        decision = committee_review(
            "X",
            risk={
                "risk_level": "high",
                "metrics": {},
                "position_recommendation": {"max_position_size": 10},
            },
            quality=None,
            audit_verdict="pass",
        )

        assert decision["verdict"] == "limit"
        assert any("5%" in condition for condition in decision["conditions"])
        assert any("stop-loss" in condition.lower() for condition in decision["conditions"])

    def test_limit_verdict_carries_the_five_percent_cap(self) -> None:
        """The limit branch must set position_cap_pct — react_agent's gate
        (`min(position_size, position_cap)`) keys off it, and without the cap
        a high-risk "Position capped at 5%" promise never binds the published
        position (review 2026-09-26, legacy P1: limit 分支漏传 cap)."""
        decision = committee_review(
            "X",
            risk={
                "risk_level": "high",
                "metrics": {},
                "position_recommendation": {"max_position_size": 10},
            },
            quality=None,
            audit_verdict="pass",
        )

        assert decision["verdict"] == "limit"
        assert decision["position_cap_pct"] == 5.0

    def test_insufficient_risk_is_watch_not_buy(self) -> None:
        decision = committee_review("X", risk=None, quality=None, audit_verdict="pass")

        assert decision["verdict"] == "watch"

    def test_approval_states_that_low_risk_is_not_a_buy_signal(self) -> None:
        decision = committee_review(
            "X",
            risk={
                "risk_level": "low",
                "metrics": {},
                "position_recommendation": {"max_position_size": 20},
            },
            quality=None,
            audit_verdict="pass",
        )

        assert decision["verdict"] == "approve"
        assert any("does NOT itself justify" in condition for condition in decision["conditions"])


class TestSynthesize:
    def test_end_to_end_shapes(self) -> None:
        data = {
            "symbols": ["AAPL"],
            "market_data": {"AAPL": {"as_of": date.today().isoformat()}},
            "technical_analysis": {"AAPL": _technical()},
            "fundamental_analysis": {"AAPL": _fundamental()},
            "sentiment_analysis": {"AAPL": {"score": 10}},
            "risk_assessment": {
                "risk_by_symbol": {  # pipeline shape
                    "AAPL": {
                        "risk_level": "medium",
                        "metrics": {"beta": 1.1},
                        "position_recommendation": {"max_position_size": 10},
                        "stress_scenarios": {"scenarios": {"market_-20pct": -0.22}},
                    }
                }
            },
        }

        result = synthesize(data)

        entry = result["per_symbol"]["AAPL"]
        assert result["audit"]["verdict"] == "pass"
        assert entry["debate"]["bull_points"]
        assert entry["committee"]["verdict"] in ("approve", "limit")


class TestReportSynthesisSection:
    def test_report_service_emits_synthesis_section(self) -> None:
        from app.services.report_service import ReportService

        data = {
            "symbols": ["AAPL"],
            "query": "analyze AAPL",
            "market_data": {"AAPL": {"as_of": date.today().isoformat(), "current_price": 100}},
            "technical_analysis": {"AAPL": _technical()},
            "fundamental_analysis": {"AAPL": _fundamental()},
            "sentiment_analysis": {"AAPL": {"score": 10}},
            "risk_assessment": {
                "AAPL": {
                    "risk_level": "medium",
                    "metrics": {"beta": 1.1},
                    "position_recommendation": {"max_position_size": 10},
                }
            },
            "research_synthesis": synthesize(
                {
                    "symbols": ["AAPL"],
                    "market_data": {"AAPL": {"as_of": date.today().isoformat()}},
                    "technical_analysis": {"AAPL": _technical()},
                    "fundamental_analysis": {"AAPL": _fundamental()},
                    "risk_assessment": {"AAPL": {"risk_level": "medium", "metrics": {}}},
                }
            ),
        }

        sections = ReportService.build_sections(data)

        section = sections["research_synthesis"]
        assert section["audit_verdict"] == "pass"
        entry = section["by_symbol"]["AAPL"]
        assert entry["committee_verdict"] in ("approve", "limit")
        assert entry["bull_points"]

    def test_report_service_omits_synthesis_when_absent(self) -> None:
        from app.services.report_service import ReportService

        sections = ReportService.build_sections({"symbols": ["AAPL"]})

        assert "research_synthesis" not in sections


class TestNarrator:
    def _synthesis(self) -> dict:
        return synthesize(
            {
                "symbols": ["AAPL"],
                "market_data": {"AAPL": {"as_of": date.today().isoformat()}},
                "technical_analysis": {"AAPL": _technical()},
                "fundamental_analysis": {"AAPL": _fundamental()},
                "risk_assessment": {"AAPL": {"risk_level": "medium", "metrics": {}}},
            }
        )

    async def _narrate(self, llm) -> dict:
        from app.research import narrate_synthesis

        return await narrate_synthesis(self._synthesis(), llm=llm)

    def test_missing_llm_degrades_to_deterministic(self) -> None:
        import asyncio

        result = asyncio.run(self._narrate(llm=None))

        assert all("narrative" not in entry for entry in result["per_symbol"].values())

    def test_valid_llm_output_attaches_narrative(self) -> None:
        import asyncio
        import json

        class FakeLLM:
            async def ainvoke(self, messages):
                from langchain_core.messages import AIMessage

                return AIMessage(
                    content=json.dumps(
                        {
                            "symbols": {
                                "AAPL": {
                                    "bull_narrative": "Up.",
                                    "bear_narrative": "Risk.",
                                    "pm_comment": "Ok.",
                                }
                            }
                        }
                    )
                )

        result = asyncio.run(self._narrate(FakeLLM()))

        narrative = result["per_symbol"]["AAPL"]["narrative"]
        assert narrative == {
            "bull_narrative": "Up.",
            "bear_narrative": "Risk.",
            "pm_comment": "Ok.",
        }

    def test_unparsable_llm_output_degrades(self) -> None:
        import asyncio

        class GarbageLLM:
            async def ainvoke(self, messages):
                from langchain_core.messages import AIMessage

                return AIMessage(content="这是一段完全没有 JSON 的散文。")

        result = asyncio.run(self._narrate(GarbageLLM()))

        assert all("narrative" not in entry for entry in result["per_symbol"].values())

    def test_llm_exception_degrades(self) -> None:
        import asyncio

        class ExplodingLLM:
            async def ainvoke(self, messages):
                raise RuntimeError("LLM down")

        result = asyncio.run(self._narrate(ExplodingLLM()))

        assert all("narrative" not in entry for entry in result["per_symbol"].values())

    def test_unknown_symbols_in_llm_output_are_dropped(self) -> None:
        import asyncio
        import json

        class InjectingLLM:
            async def ainvoke(self, messages):
                from langchain_core.messages import AIMessage

                return AIMessage(
                    content=json.dumps(
                        {
                            "symbols": {
                                "HACK": {"bull_narrative": "injected"},
                                "AAPL": {"pm_comment": "fine."},
                            }
                        }
                    )
                )

        result = asyncio.run(self._narrate(InjectingLLM()))

        assert "HACK" not in result["per_symbol"]
        assert result["per_symbol"]["AAPL"]["narrative"] == {"pm_comment": "fine."}


class TestDataUnavailableVisibility:
    """The hollow-report regression: when every data source fails, the report
    must say so instead of dressing a neutral fallback up as advice."""

    def _hollow_data(self) -> dict:
        # Shape captured from a live run where all providers failed:
        # sections keyed "_error", market block with None price and no as_of.
        return {
            "query": "分析一下 AAPL",
            "symbols": ["AAPL"],
            "market_data": {"AAPL": {"company_name": None, "current_price": None, "as_of": None}},
            "technical_analysis": {"_error": {"error": "Could not fetch data for AAPL"}},
            "fundamental_analysis": {"_error": {"error": "Could not fetch data for AAPL"}},
            "sentiment_analysis": {},
            "risk_assessment": {"_error": {"error": "Could not fetch data for AAPL"}},
        }

    def test_executive_summary_warns_instead_of_faking_hold(self) -> None:
        from app.services.report_service import ReportService

        report = ReportService.build_report(self._hollow_data())

        assert "行情数据不可用" in report["executive_summary"]
        assert "持有" not in report["executive_summary"].split("整体")[0]

    def test_audit_flags_the_hollow_report(self) -> None:
        audit = audit_packets(self._hollow_data())

        assert audit["verdict"] == "warnings"
        assert audit["insufficient"]

    def test_healthy_report_keeps_normal_summary(self) -> None:
        from app.services.report_service import ReportService

        report = ReportService.build_report(
            {
                "query": "分析一下 AAPL",
                "symbols": ["AAPL"],
                "market_data": {
                    "AAPL": {
                        "current_price": 123.45,
                        "company_name": "Apple",
                        "as_of": "2026-08-27",
                    }
                },
                "technical_analysis": {"AAPL": _technical()},
                "fundamental_analysis": {"AAPL": _fundamental()},
                "risk_assessment": {"AAPL": {"risk_level": "medium", "metrics": {}}},
            }
        )

        assert "行情数据不可用" not in report["executive_summary"]
        assert "建议" in report["executive_summary"]  # a real verdict, not the failure banner


def test_report_survives_none_fundamental_score() -> None:
    """Live-run crash: empty financials make overall_score.score None; the
    report must render 'insufficient' instead of raising on += None."""
    from app.services.report_service import ReportService

    report = ReportService.build_report(
        {
            "query": "q",
            "symbols": ["AAPL"],
            "market_data": {"AAPL": {"current_price": 314.58, "as_of": "2026-08-27"}},
            "technical_analysis": {"AAPL": _technical()},
            "fundamental_analysis": {
                "AAPL": {
                    "overall_score": {"score": None, "rating": "insufficient_data"},
                    "recommendation": "insufficient_data",
                }
            },
            "risk_assessment": {"AAPL": {"risk_level": "medium", "metrics": {}}},
        }
    )

    entry = report["sections"]["fundamental_analysis"]["by_symbol"]["AAPL"]
    assert entry["overall_score"] is None
    assert report["sections"]["fundamental_analysis"]["overall_rating"] == "hold"
