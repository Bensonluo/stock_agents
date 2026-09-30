"""Depth passthrough: the report must carry what the analysis layers compute.

Audit finding: every section builder computed or received rich data —
per-dimension metric details, growth scores, tail risk metrics, stress
scenarios, per-article sentiment scores, LLM news verdicts, snapshot depth
(52-week band, industry, business summary) — then discarded it, shipping
rating strings and six-field cards. These tests pin the wire: each block
reaches the report JSON when present, degrades to absent keys (never
exceptions or fabricated zeros) for thin symbols, and the ReAct path's
data["valuation_analysis"] map is routed into the fundamental section.
"""

from __future__ import annotations

from app.services.report_service import ReportService


def _valuation_result() -> dict:
    """scenario_valuation-shaped result as analyze_valuation returns it."""
    return {
        "symbol": "TEST",
        "status": "available",
        "as_of": "2026-09-29T00:00:00+00:00",
        "currency": "USD",
        "methods": {
            "earnings_multiple": {
                "status": "available",
                "current_pe": 20.0,
                "scenarios": {
                    "bear": {"value": 90.0, "upside_pct": -10.0, "assumptions": {}},
                    "base": {"value": 100.0, "upside_pct": 0.0, "assumptions": {}},
                    "bull": {"value": 110.0, "upside_pct": 10.0, "assumptions": {}},
                },
            }
        },
    }


def _rich_data() -> dict:
    return {
        "symbols": ["TEST"],
        "query": "TEST depth",
        "market_data": {
            "TEST": {
                "symbol": "TEST",
                "current_price": 101.0,
                "previous_close": 99.0,
                "change": 2.0,
                "change_percent": 2.02,
                "volume": 1_000_000,
                "avg_volume": 1_200_000,
                "market_cap": 5e10,
                "52_week_high": 120.0,
                "52_week_low": 60.0,
                "company_name": "Test Corp",
                "sector": "Technology",
                "industry": "Software",
                "description": "x" * 500,
                "currency": "USD",
                "as_of": "2026-09-29",
            }
        },
        "fundamental_analysis": {
            "TEST": {
                "overall_score": {"score": 66.7, "rating": "good"},
                "recommendation": "buy",
                "profitability": {
                    "score": 70.0,
                    "rating": "good",
                    "status": "available",
                    "details": {"roe": 0.18, "profit_margin": 0.12},
                },
                "valuation": {
                    "score": 55.0,
                    "rating": "fair",
                    "status": "available",
                    "details": {"pe_ratio": 22.0},
                },
                "financial_health": {
                    "score": 0,
                    "rating": "very_poor",
                    "status": "insufficient_data",
                    "details": {},
                },
                "growth": {
                    "score": 40.0,
                    "rating": "fair",
                    "status": "available",
                    "details": {"revenue_growth": 0.12},
                },
            }
        },
        "sentiment_analysis": {
            "sentiment_by_symbol": {
                "TEST": {
                    "sentiment": "positive",
                    "score": 42.0,
                    "trend": "improving",
                    "article_count": 3,
                    "recent_scores": [2, 3, 1],
                    "llm_analysis": {
                        "overall_sentiment": "positive",
                        "confidence": 80,
                        "key_factors": ["earnings beat", "analyst upgrades"],
                        "summary": "y" * 500,
                    },
                }
            },
            "overall_sentiment": {"score": 42.0},
        },
        "risk_assessment": {
            "risk_by_symbol": {
                "TEST": {
                    "symbol": "TEST",
                    "risk_score": 42.0,
                    "risk_level": "medium",
                    "metrics": {
                        "beta": 1.2,
                        "beta_status": "available",
                        "volatility_annualized": 0.31,
                        "var_95": -0.037,
                        "var_99": -0.052,
                        "cvar_95": -0.044,
                        "max_drawdown": 0.24,
                        "downside_risk": 0.019,
                        "sortino": 1.35,
                        "volatility_percentile_20d": 0.72,
                        "r_squared": 0.61,
                        "correlation": 0.78,
                        "alpha_annualized": 0.05,
                    },
                    "stress_scenarios": {
                        "status": "available",
                        "scenarios": {"market_-5pct": -0.06, "market_-10pct": -0.12},
                    },
                    "position_recommendation": {"max_position_size": 10.0},
                    "warnings": [],
                }
            },
            "portfolio_risk": {},
            "overall_risk_level": "medium",
        },
    }


def _thin_data() -> dict:
    """Degraded shapes: mirrors _minimal_risk / empty_sentiment / no metrics."""
    return {
        "symbols": ["TEST"],
        "query": "TEST thin",
        "market_data": {"TEST": {"symbol": "TEST", "current_price": None}},
        "fundamental_analysis": {
            "TEST": {
                "overall_score": {"score": None, "rating": "insufficient_data"},
                "recommendation": "insufficient_data",
                "profitability": {
                    "score": 0,
                    "rating": "very_poor",
                    "status": "insufficient_data",
                    "details": {},
                },
                "financial_health": {
                    "score": 0,
                    "rating": "very_poor",
                    "status": "insufficient_data",
                    "details": {},
                },
            }
        },
        "sentiment_analysis": {
            "sentiment_by_symbol": {
                "TEST": {
                    "sentiment": "neutral",
                    "score": 0,
                    "article_count": 0,
                    "recent_scores": [],
                    "trend": "no_data",
                }
            },
            "overall_sentiment": {},
        },
        "risk_assessment": {
            "risk_by_symbol": {
                "TEST": {
                    "symbol": "TEST",
                    "risk_score": None,
                    "risk_level": "insufficient_data",
                    "risk_score_status": "insufficient_data",
                    "metrics": {"beta": None, "beta_status": "insufficient_data"},
                    "position_recommendation": {
                        "max_position_size": None,
                        "status": "insufficient_data",
                    },
                    "warnings": ["Insufficient data for detailed risk assessment"],
                }
            },
            "portfolio_risk": {},
            "overall_risk_level": "medium",
        },
    }


class TestOverviewDepth:
    def test_snapshot_depth_reaches_the_report(self) -> None:
        info = ReportService.build_sections(_rich_data())["overview"]["market_summary"]["TEST"]

        assert info["previous_close"] == 99.0
        assert info["avg_volume"] == 1_200_000
        assert info["52_week_high"] == 120.0
        assert info["52_week_low"] == 60.0
        assert info["industry"] == "Software"
        # Business summary is capped to keep the payload sane.
        assert info["description"] == "x" * 200

    def test_thin_block_reports_none_not_garbage(self) -> None:
        info = ReportService.build_sections(_thin_data())["overview"]["market_summary"]["TEST"]

        assert info["description"] is None
        assert info["52_week_high"] is None
        assert info["avg_volume"] is None


class TestFundamentalDepth:
    def test_dimension_scores_and_metric_details_reach_the_report(self) -> None:
        card = ReportService.build_sections(_rich_data())["fundamental_analysis"]["by_symbol"][
            "TEST"
        ]

        assert card["profitability_score"] == 70.0
        assert card["profitability_details"] == {"roe": 0.18, "profit_margin": 0.12}
        assert card["valuation_score"] == 55.0
        assert card["valuation_details"] == {"pe_ratio": 22.0}
        # The growth component (scored on its own achievable maximum).
        assert card["growth"] == {
            "score": 40.0,
            "rating": "fair",
            "details": {"revenue_growth": 0.12},
        }

    def test_insufficient_dimensions_add_no_keys(self) -> None:
        card = ReportService.build_sections(_rich_data())["fundamental_analysis"]["by_symbol"][
            "TEST"
        ]

        # financial_health ran with zero measurable metrics: no fabricated
        # score, no empty details dict on the wire.
        assert "financial_health_score" not in card
        assert "financial_health_details" not in card

    def test_thin_symbol_degrades_to_rating_strings_only(self) -> None:
        card = ReportService.build_sections(_thin_data())["fundamental_analysis"]["by_symbol"][
            "TEST"
        ]

        assert card["overall_score"] is None
        for key in (
            "profitability_score",
            "profitability_details",
            "financial_health_details",
            "growth",
        ):
            assert key not in card


class TestSentimentDepth:
    def test_recent_scores_and_llm_verdict_reach_the_report(self) -> None:
        card = ReportService.build_sections(_rich_data())["sentiment_analysis"]["by_symbol"]["TEST"]

        assert card["recent_scores"] == [2, 3, 1]
        assert card["llm_analysis"]["overall_sentiment"] == "positive"
        assert card["llm_analysis"]["confidence"] == 80
        # Long summaries ride capped, not dropped and not full-length.
        assert card["llm_analysis"]["summary"] == "y" * 200

    def test_thin_feed_gains_no_depth_keys(self) -> None:
        card = ReportService.build_sections(_thin_data())["sentiment_analysis"]["by_symbol"]["TEST"]

        assert "recent_scores" not in card
        assert "llm_analysis" not in card


class TestRiskDepth:
    def test_tail_metrics_and_stress_scenarios_reach_the_report(self) -> None:
        card = ReportService.build_sections(_rich_data())["risk_analysis"]["by_symbol"]["TEST"]

        assert card["var_99"] == -0.052
        assert card["cvar_95"] == -0.044
        assert card["sortino"] == 1.35
        assert card["downside_risk"] == 0.019
        assert card["volatility_percentile_20d"] == 0.72
        assert card["r_squared"] == 0.61
        assert card["correlation"] == 0.78
        # Compact scenario→implied-move map from the beta-scaled shocks.
        assert card["stress_scenarios"] == {"market_-5pct": -0.06, "market_-10pct": -0.12}

    def test_degraded_entry_gains_no_depth_keys(self) -> None:
        card = ReportService.build_sections(_thin_data())["risk_analysis"]["by_symbol"]["TEST"]

        for key in (
            "var_99",
            "cvar_95",
            "sortino",
            "downside_risk",
            "volatility_percentile_20d",
            "r_squared",
            "correlation",
            "stress_scenarios",
        ):
            assert key not in card


class TestReactValuationRouting:
    def test_valuation_analysis_yields_scenarios_in_fundamental_section(self) -> None:
        data = {
            "symbols": ["TEST"],
            "query": "TEST react",
            "market_data": {"TEST": {"symbol": "TEST", "current_price": 101.0}},
            "valuation_analysis": {"TEST": _valuation_result()},
        }

        card = ReportService.build_sections(data)["fundamental_analysis"]["by_symbol"]["TEST"]

        scenarios = card["valuation_scenarios"]
        assert scenarios["status"] == "available"
        assert scenarios["scenarios"]["bear"]["earnings_multiple"]["value"] == 90.0
        assert scenarios["scenarios"]["bull"]["earnings_multiple"]["upside_pct"] == 10.0

    def test_existing_fundamental_entry_gains_scenarios_without_clobber(self) -> None:
        fundamental = {"TEST": {"overall_score": {"score": 50.0, "rating": "fair"}}}
        data = {
            "symbols": ["TEST"],
            "query": "TEST react",
            "fundamental_analysis": fundamental,
            "valuation_analysis": {"TEST": _valuation_result()},
        }

        card = ReportService.build_sections(data)["fundamental_analysis"]["by_symbol"]["TEST"]

        assert card["overall_score"] == 50.0
        assert card["valuation_scenarios"]["status"] == "available"
        # The normalizer must not mutate the caller's data — it runs more
        # than once per report on the same dict.
        assert "valuation_scenarios" not in fundamental["TEST"]

    def test_failed_valuation_tool_does_not_crash_the_report(self) -> None:
        # ReAct parks error responses under "_error" in the tool bucket —
        # no per-symbol result, so no fundamental card is manufactured.
        data = {
            "symbols": ["TEST"],
            "query": "TEST react",
            "valuation_analysis": {"_error": {"error": "fetch failed"}},
        }

        by_symbol = ReportService.build_sections(data)["fundamental_analysis"]["by_symbol"]

        assert by_symbol == {}


class TestRiskEvidenceWiring:
    def test_headline_risk_numbers_get_evidence_records(self) -> None:
        records = ReportService.build_sections(_rich_data())["evidence_index"]["TEST"]

        by_name = {record["name"]: record for record in records}
        for name in ("volatility_annualized", "beta", "cvar_95", "sortino"):
            assert name in by_name
            assert by_name[name]["source"] == "market_data_history"
            assert by_name[name]["formula"]
            assert by_name[name]["value"] is not None

    def test_thin_symbol_falls_back_to_availability_record(self) -> None:
        records = ReportService.build_sections(_thin_data())["evidence_index"]["TEST"]

        # No usable risk metrics (beta None, status string) → no risk
        # evidence; the drawer still covers the symbol explicitly.
        assert records == [
            {
                "source": "data_availability",
                "note": "no analyzable market data; decision degraded",
            }
        ]

    def test_metrics_without_a_usable_cutoff_produce_no_records(self) -> None:
        data = _rich_data()
        data["market_data"]["TEST"]["as_of"] = None

        records = ReportService.build_sections(data)["evidence_index"]["TEST"]

        # risk_evidence honestly returns nothing without a data cutoff; the
        # technical/fundamental evidence (none here) leaves the fallback.
        assert records == [
            {
                "source": "data_availability",
                "note": "no analyzable market data; decision degraded",
            }
        ]
