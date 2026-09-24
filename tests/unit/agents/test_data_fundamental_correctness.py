"""Regression tests for data-window and fundamental-score correctness."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest


def _load_agent_module(module_name: str):
    """Load an agent module without exercising the app's unrelated package cycle."""
    base_module = ModuleType("app.agents.base")
    base_module.BaseAgent = type("BaseAgent", (), {})
    state_module = ModuleType("app.orchestration.state")
    state_module.AgentState = dict
    replaced = {
        name: sys.modules.get(name) for name in ("app.agents.base", "app.orchestration.state")
    }
    sys.modules.update({"app.agents.base": base_module, "app.orchestration.state": state_module})
    try:
        module_path = Path(__file__).parents[3] / "app" / "agents" / f"{module_name}.py"
        spec = importlib.util.spec_from_file_location(f"{module_name}_under_test", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, original in replaced.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


data_agent = _load_agent_module("data_agent")
analysis_agent = _load_agent_module("analysis_agent")
FundamentalAnalysisAgent = analysis_agent.FundamentalAnalysisAgent


class _FakeTicker:
    def __init__(self, info: dict, history_calls: list[dict] | None = None):
        self.info = info
        self._history_calls = history_calls if history_calls is not None else []
        self.income_stmt = pd.DataFrame()
        self.balance_sheet = pd.DataFrame()
        self.cashflow = pd.DataFrame()
        self.earnings_dates = None

    def history(self, **kwargs):
        self._history_calls.append(kwargs)
        index = pd.to_datetime(["2024-01-02", "2024-01-03"])
        return pd.DataFrame(
            {
                "Open": [99.0, 100.0],
                "High": [101.0, 102.0],
                "Low": [98.0, 99.0],
                "Close": [100.0, 101.0],
                "Volume": [1_000, 1_100],
            },
            index=index,
        )


def test_data_agent_fetches_at_least_three_years_for_indicator_warmup(monkeypatch) -> None:
    history_calls: list[dict] = []
    ticker = _FakeTicker({"currentPrice": 101.0, "previousClose": 100.0}, history_calls)
    monkeypatch.setattr(data_agent.yf, "Ticker", lambda _symbol: ticker)

    data_agent._sync_fetch_market_data("AAPL", "AAPL", lambda _df: {})

    requested_window = history_calls[0]["end"] - history_calls[0]["start"]
    assert requested_window.days >= 3 * 365


def test_yfinance_metrics_are_exposed_as_decimal_ratios(monkeypatch) -> None:
    ticker = _FakeTicker(
        {
            "returnOnEquity": 0.20,
            "returnOnAssets": 0.10,
            "profitMargins": 0.15,
            "operatingMargins": 0.12,
            "debtToEquity": 75.0,
        }
    )
    monkeypatch.setattr(data_agent.yf, "Ticker", lambda _symbol: ticker)

    result = data_agent._sync_fetch_financial_data("AAPL", "AAPL", lambda _df: {})

    assert result["metrics"]["roe"] == pytest.approx(0.20)
    assert result["metrics"]["roa"] == pytest.approx(0.10)
    assert result["metrics"]["profit_margin"] == pytest.approx(0.15)
    assert result["metrics"]["operating_margin"] == pytest.approx(0.12)
    assert result["metrics"]["debt_to_equity"] == pytest.approx(0.75)
    assert result["metric_units"]["debt_to_equity"] == "ratio"


def _fundamental_agent() -> FundamentalAnalysisAgent:
    # The scoring helpers are pure and do not require BaseAgent runtime services.
    return FundamentalAnalysisAgent.__new__(FundamentalAnalysisAgent)


def test_agent_uses_decimal_ratio_thresholds_for_profitability() -> None:
    result = _fundamental_agent()._analyze_profitability(
        {
            "roe": 0.20,
            "roa": 0.10,
            "profit_margin": 0.20,
            "operating_margin": 0.15,
        }
    )

    assert result["score"] == 100
    assert result["status"] == "available"


def test_missing_growth_is_not_replaced_with_a_neutral_score() -> None:
    result = _fundamental_agent()._analyze_growth({})

    assert result["score"] is None
    assert result["rating"] == "insufficient_data"
    assert result["status"] == "insufficient_data"


def test_available_fundamental_weights_are_renormalized_without_growth() -> None:
    agent = _fundamental_agent()
    available = {"score": 100, "status": "available"}
    missing = {"score": None, "status": "insufficient_data"}

    result = agent._calculate_overall_score(available, available, available, missing)

    assert result["score"] == 100
    assert result["status"] == "partial"
    assert result["available_weight"] == pytest.approx(0.90)


def test_empty_fundamentals_do_not_generate_strong_sell() -> None:
    agent = _fundamental_agent()
    missing = {"score": None, "status": "insufficient_data"}

    overall = agent._calculate_overall_score(missing, missing, missing, missing)

    assert overall["score"] is None
    assert overall["status"] == "insufficient_data"
    assert agent._generate_recommendation(overall) == "insufficient_data"


def test_earnings_dates_survive_the_financial_fetch(monkeypatch) -> None:
    """The stored calendar keeps its dates — the whole point of the fix.

    ``to_dict("records")`` dropped the DatetimeIndex, leaving EPS estimates
    attached to nothing; earnings_records resets the index first.
    """
    ticker = _FakeTicker({"trailingPE": 10.0})
    ticker.earnings_dates = pd.DataFrame(
        {"EPS Estimate": [1.2, 1.3], "Surprise(%)": [4.0, -1.0]},
        index=pd.DatetimeIndex(["2026-06-30", "2026-09-30"]),
    )
    monkeypatch.setattr(data_agent.yf, "Ticker", lambda _symbol: ticker)

    financial = data_agent._sync_fetch_financial_data("AAPL", "AAPL", lambda _df: {})

    assert [record["date"] for record in financial["earnings_dates"]] == [
        "2026-06-30",
        "2026-09-30",
    ]
    assert financial["earnings_dates"][0]["eps_estimate"] == 1.2
