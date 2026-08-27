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
    return {"overall_score": {"score": 70}, "quality": quality}


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
                red_flags=[{"code": "negative_cfo_positive_ni", "severity": "critical", "detail": "Profit without cash."}]
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
    def test_fresh_data_passes(self) -> None:
        data = {"market_data": {"AAPL": {"as_of": date.today().isoformat()}}}

        audit = audit_packets(data)

        assert audit["verdict"] == "pass"
        assert audit["stale"] == []

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
                    red_flags=[{"code": "negative_equity", "severity": "critical", "detail": "Negative equity."}]
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
            risk={"risk_level": "high", "metrics": {}, "position_recommendation": {"max_position_size": 10}},
            quality=None,
            audit_verdict="pass",
        )

        assert decision["verdict"] == "limit"
        assert any("5%" in condition for condition in decision["conditions"])
        assert any("stop-loss" in condition.lower() for condition in decision["conditions"])

    def test_insufficient_risk_is_watch_not_buy(self) -> None:
        decision = committee_review("X", risk=None, quality=None, audit_verdict="pass")

        assert decision["verdict"] == "watch"

    def test_approval_states_that_low_risk_is_not_a_buy_signal(self) -> None:
        decision = committee_review(
            "X",
            risk={"risk_level": "low", "metrics": {}, "position_recommendation": {"max_position_size": 20}},
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
                    "risk_assessment": {
                        "AAPL": {"risk_level": "medium", "metrics": {}}
                    },
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
                        {"symbols": {"AAPL": {"bull_narrative": "Up.", "bear_narrative": "Risk.", "pm_comment": "Ok."}}}
                    )
                )

        result = asyncio.run(self._narrate(FakeLLM()))

        narrative = result["per_symbol"]["AAPL"]["narrative"]
        assert narrative == {"bull_narrative": "Up.", "bear_narrative": "Risk.", "pm_comment": "Ok."}

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
                        {"symbols": {"HACK": {"bull_narrative": "injected"}, "AAPL": {"pm_comment": "fine."}}}
                    )
                )

        result = asyncio.run(self._narrate(InjectingLLM()))

        assert "HACK" not in result["per_symbol"]
        assert result["per_symbol"]["AAPL"]["narrative"] == {"pm_comment": "fine."}
