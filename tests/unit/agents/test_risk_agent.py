"""Specification tests for evidence-based risk assessment."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest


def _load_risk_agent_class() -> type:
    """Load the target module without exercising the app's unrelated package cycle."""
    base_module = ModuleType("app.agents.base")
    base_module.StatelessAgent = type("StatelessAgent", (), {})
    state_module = ModuleType("app.orchestration.state")
    state_module.AgentState = dict

    replaced = {
        name: sys.modules.get(name) for name in ("app.agents.base", "app.orchestration.state")
    }
    sys.modules.update({"app.agents.base": base_module, "app.orchestration.state": state_module})
    try:
        module_path = Path(__file__).parents[3] / "app" / "agents" / "risk_agent.py"
        spec = importlib.util.spec_from_file_location("risk_agent_under_test", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.RiskAssessmentAgent
    finally:
        for name, original in replaced.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


RiskAssessmentAgent = _load_risk_agent_class()


def _history(returns: np.ndarray, *, start_offset: int = 0) -> dict[str, list]:
    prices = [100.0]
    for value in returns:
        prices.append(prices[-1] * (1 + float(value)))

    start = date(2024, 1, 1) + timedelta(days=start_offset)
    dates = [(start + timedelta(days=index)).isoformat() for index in range(len(prices))]
    return {"dates": dates, "close": prices}


def test_estimate_beta_uses_benchmark_returns() -> None:
    agent = RiskAssessmentAgent()
    benchmark_returns = np.array(
        [
            -0.012,
            0.008,
            0.015,
            -0.006,
            0.004,
            0.011,
            -0.009,
            0.007,
            0.013,
            -0.004,
            0.006,
            -0.011,
            0.014,
            0.003,
            -0.007,
            0.009,
            -0.005,
            0.012,
            -0.008,
            0.005,
        ]
    )

    beta = agent._estimate_beta(benchmark_returns * 1.75, benchmark_returns)

    assert beta == pytest.approx(1.75)


@pytest.mark.parametrize(
    ("benchmark_returns", "stock_returns"),
    [
        (None, np.arange(20, dtype=float)),
        (np.ones(20), np.arange(20, dtype=float)),
        (np.arange(10, dtype=float), np.arange(10, dtype=float)),
    ],
)
def test_estimate_beta_returns_none_without_sufficient_market_evidence(
    benchmark_returns: np.ndarray | None,
    stock_returns: np.ndarray,
) -> None:
    agent = RiskAssessmentAgent()

    assert agent._estimate_beta(stock_returns, benchmark_returns) is None


def test_risk_score_accepts_missing_beta_without_inventing_a_default() -> None:
    agent = RiskAssessmentAgent()

    score = agent._calculate_risk_score(
        {"volatility": 0.02, "max_drawdown": 0.2, "var_95": -0.03, "beta": None}
    )

    assert score == 55


def test_risk_score_and_position_remain_unknown_when_core_metrics_are_missing() -> None:
    agent = RiskAssessmentAgent()

    score = agent._calculate_risk_score(
        {"volatility": None, "max_drawdown": 0.2, "var_95": -0.03, "beta": None}
    )

    assert score is None
    assert agent._risk_score_to_level(score) == "insufficient_data"
    assert agent._calculate_position_size(score) is None


def test_portfolio_summary_ignores_unknown_scores_without_inventing_an_average() -> None:
    agent = RiskAssessmentAgent()

    result = agent._assess_portfolio_risk(
        {
            "UNKNOWN": {
                "risk_score": None,
                "risk_level": "insufficient_data",
            }
        }
    )

    assert result["avg_risk_score"] is None
    assert result["portfolio_risk_level"] == "insufficient_data"


@pytest.mark.asyncio
async def test_assessment_marks_score_partial_and_withholds_position_without_benchmark() -> None:
    agent = RiskAssessmentAgent()
    stock_returns = np.linspace(-0.02, 0.025, 24)

    result = await agent._assess_risk(
        "TEST",
        {"symbol": "TEST", "historical_data": _history(stock_returns)},
    )

    assert result["metrics"]["beta"] is None
    assert result["metrics"]["beta_status"] == "insufficient_data"
    assert result["risk_score_status"] == "partial"
    assert result["position_recommendation"]["max_position_size"] is None
    assert "benchmark" in " ".join(result["warnings"]).lower()


@pytest.mark.asyncio
async def test_assessment_calculates_beta_from_aligned_benchmark_history() -> None:
    agent = RiskAssessmentAgent()
    benchmark_returns = np.array(
        [(-1 if index % 3 == 0 else 1) * (0.003 + index * 0.0004) for index in range(24)]
    )
    stock_returns = benchmark_returns * 1.4

    result = await agent._assess_risk(
        "TEST",
        {
            "symbol": "TEST",
            "historical_data": _history(stock_returns),
            "benchmark_historical_data": _history(benchmark_returns),
        },
    )

    assert result["metrics"]["beta"] == pytest.approx(1.4)
    assert result["metrics"]["beta_status"] == "available"
    assert result["risk_score_status"] == "complete"
    assert result["position_recommendation"]["max_position_size"] is not None


@pytest.mark.asyncio
async def test_insufficient_price_history_does_not_claim_numeric_risk_or_position() -> None:
    agent = RiskAssessmentAgent()

    result = await agent._assess_risk(
        "TEST",
        {"symbol": "TEST", "historical_data": _history(np.array([0.01, -0.01]))},
    )

    assert result["risk_score"] is None
    assert result["risk_level"] == "insufficient_data"
    assert result["position_recommendation"]["max_position_size"] is None


def test_diversification_score_discounts_by_measured_correlation() -> None:
    agent = RiskAssessmentAgent()
    three = {s: {"risk_score": 40} for s in ("AAA", "BBB", "CCC")}  # tier 40

    assert agent._calculate_diversification_score(three) == 40  # legacy, no evidence
    assert agent._calculate_diversification_score(three, 0.25) == 30  # 40 * 0.75
    assert agent._calculate_diversification_score(three, 1.0) == 0  # nothing diversified
    assert agent._calculate_diversification_score(three, -1.0) == 80  # 40 * 2

    twenty = {f"S{i}": {"risk_score": 40} for i in range(20)}  # tier 100
    assert agent._calculate_diversification_score(twenty, -0.5) == 100  # 150 -> clamped


def test_portfolio_summary_without_histories_reports_insufficient_correlations() -> None:
    agent = RiskAssessmentAgent()

    result = agent._assess_portfolio_risk(
        {
            "AAA": {"risk_score": 40, "risk_level": "medium"},
            "BBB": {"risk_score": 40, "risk_level": "medium"},
        }
    )

    assert result["correlations"]["status"] == "insufficient_data"
    assert result["avg_pairwise_correlation"] is None
    assert result["diversification_score"] == 20  # count tier unchanged


@pytest.mark.asyncio
async def test_portfolio_summary_discounts_diversification_by_correlation() -> None:
    agent = RiskAssessmentAgent()
    returns = np.array([0.02, -0.01] * 12)  # 24 alternating days, dates align

    result = await agent.process(
        {
            "symbols": ["AAA", "BBB"],
            "market_data": {
                "AAA": {"symbol": "AAA", "historical_data": _history(returns)},
                # 1.5x the same returns -> pairwise correlation exactly 1.0
                "BBB": {"symbol": "BBB", "historical_data": _history(returns * 1.5)},
            },
        }
    )

    portfolio = result["portfolio_risk"]
    assert portfolio["correlations"]["pairs"] == {"AAA|BBB": 1.0}
    assert portfolio["avg_pairwise_correlation"] == 1.0
    assert portfolio["diversification_score"] == 0  # 20 * (1 - 1)


@pytest.mark.asyncio
async def test_negative_correlation_lifts_diversification_score() -> None:
    agent = RiskAssessmentAgent()
    returns = np.array([0.02, -0.01] * 12)

    result = await agent.process(
        {
            "symbols": ["AAA", "BBB"],
            "market_data": {
                "AAA": {"symbol": "AAA", "historical_data": _history(returns)},
                "BBB": {"symbol": "BBB", "historical_data": _history(-returns / 2)},
            },
        }
    )

    portfolio = result["portfolio_risk"]
    assert portfolio["avg_pairwise_correlation"] == -1.0
    assert portfolio["diversification_score"] == 40  # 20 * (1 - (-1))


@pytest.mark.asyncio
async def test_short_histories_keep_count_based_diversification() -> None:
    agent = RiskAssessmentAgent()
    returns = np.array([0.02, -0.01] * 5)  # 10 returns < 20-observation guard

    result = await agent.process(
        {
            "symbols": ["AAA", "BBB"],
            "market_data": {
                "AAA": {"symbol": "AAA", "historical_data": _history(returns)},
                "BBB": {"symbol": "BBB", "historical_data": _history(returns)},
            },
        }
    )

    portfolio = result["portfolio_risk"]
    assert portfolio["correlations"]["status"] == "insufficient_data"
    assert portfolio["avg_pairwise_correlation"] is None
    assert portfolio["diversification_score"] == 20  # legacy count tier


def test_market_regime_reads_the_benchmark_not_the_symbol() -> None:
    agent = RiskAssessmentAgent()
    # Benchmark grinding up 0.2%/bar; the symbol itself is irrelevant —
    # the regime block speaks for the market, not any single name.
    market_data = {
        "TEST": {
            "symbol": "TEST",
            "historical_data": _history(np.linspace(-0.01, 0.01, 30)),
            "benchmark_historical_data": _history(np.linspace(0.001, 0.003, 299)),
        }
    }

    regime = agent._market_regime(market_data)

    assert regime is not None
    assert regime["trend"] == "bull"
    assert regime["volatility_regime"] is not None


def test_market_regime_refuses_without_a_usable_benchmark() -> None:
    agent = RiskAssessmentAgent()
    # No benchmark attached (pre-iteration-31 legacy state) → None.
    assert agent._market_regime({"TEST": {"symbol": "TEST"}}) is None
    # Benchmark too short to classify → honest refusal, not a guessed regime.
    short = _history(np.full(40, 0.01))
    assert agent._market_regime({"TEST": {"benchmark_historical_data": short}}) is None


@pytest.mark.asyncio
async def test_process_attaches_market_regime_alongside_risk() -> None:
    agent = RiskAssessmentAgent()
    market_data = {
        "TEST": {
            "symbol": "TEST",
            "historical_data": _history(np.linspace(-0.02, 0.025, 24)),
            "benchmark_historical_data": _history(np.linspace(0.001, 0.003, 299)),
        }
    }

    result = await agent.process({"market_data": market_data, "symbols": ["TEST"]})

    assert "TEST" in result["risk_by_symbol"]
    assert result["market_regime"] is not None
    assert result["market_regime"]["trend"] == "bull"
