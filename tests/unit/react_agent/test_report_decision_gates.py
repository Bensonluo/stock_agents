from app.react_agent import react_agent


def _synthesis(verdict: str, cap: float | None = None) -> dict:
    return {
        "audit": {"verdict": "pass"},
        "per_symbol": {
            "TEST": {
                "committee": {
                    "verdict": verdict,
                    "position_cap_pct": cap,
                    "conditions": [],
                }
            }
        },
    }


def test_low_risk_and_large_position_do_not_create_buy(monkeypatch) -> None:
    monkeypatch.setattr(react_agent, "synthesize", lambda data: _synthesis("approve", 15.0))
    state = {
        "symbols": ["TEST"],
        "tool_results": {
            "assess_risk": {
                "TEST": {
                    "risk_level": "low",
                    "risk_score": 20,
                    "position_recommendation": {"max_position_size": 15.0},
                }
            },
            "calculate_position_size": {"TEST": {"position_size": 15.0}},
        },
    }

    decision = react_agent._build_report_data(state)["decision"]["decisions"]["TEST"]

    assert decision["action"] == "hold"
    assert decision["committee_verdict"] == "approve"


def test_committee_veto_blocks_positive_evidence(monkeypatch) -> None:
    monkeypatch.setattr(react_agent, "synthesize", lambda data: _synthesis("veto"))
    state = {
        "symbols": ["TEST"],
        "tool_results": {
            "analyze_technical": {
                "TEST": {"signals": {"trend": "bullish"}, "sentiment": {"score": 80}}
            },
            "analyze_fundamental": {
                "TEST": {"overall_score": 90, "recommendation": "buy"}
            },
            "analyze_sentiment": {
                "TEST": {"sentiment": {"score": 80}, "overall_sentiment": {}}
            },
            "assess_risk": {"TEST": {"risk_level": "low", "risk_score": 20}},
            "calculate_position_size": {"TEST": {"position_size": 20.0}},
        },
    }

    decision = react_agent._build_report_data(state)["decision"]["decisions"]["TEST"]

    assert decision["action"] == "hold"
    assert decision["position_size"] == 0.0
    assert decision["committee_verdict"] == "veto"


def test_technical_fallback_reconstructs_market_overview(monkeypatch) -> None:
    monkeypatch.setattr(react_agent, "synthesize", lambda data: _synthesis("watch"))
    state = {
        "symbols": ["TEST"],
        "tool_results": {
            "analyze_technical": {
                "TEST": {
                    "current_price": 123.45,
                    "weekly_sma": {"as_of": "2026-08-29"},
                }
            },
            "assess_risk": {"TEST": {"risk_level": "medium", "risk_score": 50}},
        },
    }

    report_data = react_agent._build_report_data(state)

    assert report_data["market_data"]["TEST"] == {
        "symbol": "TEST",
        "current_price": 123.45,
        "as_of": "2026-08-29",
    }
