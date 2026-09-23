"""Tests for the evidence-constrained analyst panel (V2 plan §6)."""

from __future__ import annotations

import asyncio
import json
from datetime import date

from app.research import attach_analyst_panel, synthesize


def _technical(*, trend: str = "bullish", score: int = 40) -> dict:
    return {
        "status": "available",
        "signals": {"trend": trend},
        "sentiment": {"score": score},
        "weekly_sma": {"alignment": {"state": "bullish", "weeks_in_state": 12}},
    }


def _synthesis() -> dict:
    return synthesize(
        {
            "symbols": ["AAPL"],
            "market_data": {"AAPL": {"as_of": date.today().isoformat()}},
            "technical_analysis": {"AAPL": _technical()},
            "fundamental_analysis": {
                "AAPL": {
                    "overall_score": {"score": 70},
                    "quality": {"status": "available", "red_flags": []},
                }
            },
            "risk_assessment": {"AAPL": {"risk_level": "medium", "metrics": {}}},
        }
    )


def _llm_responding(payload: dict) -> object:
    class FakeLLM:
        async def ainvoke(self, messages):
            from langchain_core.messages import AIMessage

            return AIMessage(content=json.dumps({"symbols": payload}, ensure_ascii=False))

    return FakeLLM()


class TestAnalystPanel:
    def test_missing_llm_degrades(self) -> None:
        result = asyncio.run(attach_analyst_panel(_synthesis(), llm=None))

        assert all("analysts" not in e and "pm" not in e for e in result["per_symbol"].values())

    def test_valid_panel_attaches_roles_and_pm(self) -> None:
        panel = {
            "AAPL": {
                "technical": {
                    "view": "Trend intact.",
                    "cites": ["technical_analysis.signals+weekly_sma"],
                },
                "fundamental": {
                    "view": "Quality fine.",
                    "cites": ["technical_analysis.signals+weekly_sma"],
                },
                "valuation": {
                    "view": "Range wide.",
                    "cites": ["technical_analysis.signals+weekly_sma"],
                },
                "event": {"view": "None due.", "cites": ["technical_analysis.signals+weekly_sma"]},
                "pm": {
                    "thesis": "Hold with discipline.",
                    "horizon": "medium",
                    "conditions": ["Respect 5% cap"],
                    "invalidation": "Weekly alignment flips",
                    "committee_verdict": "approve",
                },
            }
        }

        result = asyncio.run(attach_analyst_panel(_synthesis(), llm=_llm_responding(panel)))

        entry = result["per_symbol"]["AAPL"]
        assert set(entry["analysts"]) == {"technical", "fundamental", "valuation", "event"}
        assert entry["pm"]["committee_verdict"] == "approve"
        assert entry["pm"]["thesis"] == "Hold with discipline."

    def test_unknown_citation_gets_role_dropped(self) -> None:
        panel = {
            "AAPL": {
                "technical": {"view": "Made-up source.", "cites": ["fabricated_ref"]},
                "fundamental": {
                    "view": "Fine.",
                    "cites": ["technical_analysis.signals+weekly_sma"],
                },
            }
        }

        result = asyncio.run(attach_analyst_panel(_synthesis(), llm=_llm_responding(panel)))

        analysts = result["per_symbol"]["AAPL"]["analysts"]
        assert "technical" not in analysts
        assert "fundamental" in analysts

    def test_empty_citations_dropped(self) -> None:
        panel = {"AAPL": {"technical": {"view": "No cites.", "cites": []}}}

        result = asyncio.run(attach_analyst_panel(_synthesis(), llm=_llm_responding(panel)))

        assert all("analysts" not in e for e in result["per_symbol"].values())

    def test_pm_not_restating_verdict_is_dropped(self) -> None:
        panel = {
            "AAPL": {
                "pm": {
                    "thesis": "Buy everything.",
                    "committee_verdict": "strong_buy",  # actual verdict is "approve"
                }
            }
        }

        result = asyncio.run(attach_analyst_panel(_synthesis(), llm=_llm_responding(panel)))

        entry = result["per_symbol"]["AAPL"]
        assert "pm" not in entry

    def test_garbage_output_degrades(self) -> None:
        class GarbageLLM:
            async def ainvoke(self, messages):
                from langchain_core.messages import AIMessage

                return AIMessage(content="no json here")

        result = asyncio.run(attach_analyst_panel(_synthesis(), llm=GarbageLLM()))

        assert all("analysts" not in e for e in result["per_symbol"].values())

    def test_llm_exception_degrades(self) -> None:
        class ExplodingLLM:
            async def ainvoke(self, messages):
                raise RuntimeError("down")

        result = asyncio.run(attach_analyst_panel(_synthesis(), llm=ExplodingLLM()))

        assert all("analysts" not in e for e in result["per_symbol"].values())
