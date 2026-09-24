"""Regression tests for the ReAct data and fundamental tools."""

from __future__ import annotations

import pandas as pd
import pytest

from app.tools.analysis import auto_tools
from app.tools.analysis.fundamental import analyze_fundamental
from app.tools.data import fetcher


class _FakeYFinanceTicker:
    def __init__(self, info: dict, history_calls: list[dict]):
        self.info = info
        self.news = []
        self._history_calls = history_calls

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


@pytest.mark.asyncio
async def test_fetcher_yfinance_uses_three_year_window_and_normalizes_debt(monkeypatch) -> None:
    import yfinance as yf

    history_calls: list[dict] = []
    ticker = _FakeYFinanceTicker(
        {
            "currentPrice": 101.0,
            "previousClose": 100.0,
            "returnOnEquity": 0.20,
            "returnOnAssets": 0.10,
            "profitMargins": 0.15,
            "operatingMargins": 0.12,
            "debtToEquity": 75.0,
        },
        history_calls,
    )
    monkeypatch.setattr(yf, "Ticker", lambda _symbol: ticker)

    result = await fetcher._yfinance_fetch("AAPL")

    requested_window = history_calls[0]["end"] - history_calls[0]["start"]
    metrics = result["financial_data"]["metrics"]
    assert requested_window.days >= 3 * 365
    assert metrics["roe"] == pytest.approx(0.20)
    assert metrics["debt_to_equity"] == pytest.approx(0.75)
    assert result["financial_data"]["metric_units"]["roe"] == "ratio"


@pytest.mark.asyncio
async def test_fetch_historical_defaults_to_three_years(monkeypatch) -> None:
    import yfinance as yf

    fetcher._cache.clear()
    history_calls: list[dict] = []
    ticker = _FakeYFinanceTicker({}, history_calls)
    monkeypatch.setattr(yf, "Ticker", lambda _symbol: ticker)

    result = await fetcher.fetch_historical("WINDOW_TEST")

    assert history_calls == [{"period": "3y"}]
    assert result["period"] == "3y"


@pytest.mark.asyncio
async def test_auto_tool_requests_three_year_fallback_history(monkeypatch) -> None:
    requested_periods: list[str] = []

    async def fake_stock_data(_symbol: str):
        return {
            "market_data": {"current_price": 10.0, "historical_data": {}},
            "financial_data": {"metrics": {}},
            "news_data": [],
        }

    async def fake_history(_symbol: str, period: str):
        requested_periods.append(period)
        return {
            "dates": ["2024-01-01"],
            "open": [10.0],
            "high": [10.0],
            "low": [10.0],
            "close": [10.0],
            "volume": [100],
        }

    monkeypatch.setattr(auto_tools, "fetch_stock_data", fake_stock_data)
    monkeypatch.setattr(auto_tools, "fetch_historical", fake_history)

    async def no_benchmark(ticker):
        return None  # offline test: benchmark absence is the degraded case

    monkeypatch.setattr(auto_tools, "fetch_benchmark_history", no_benchmark)

    await auto_tools._fetch_and_split("AAPL")

    assert requested_periods == ["3y"]


def test_react_fundamental_tool_renormalizes_around_missing_growth() -> None:
    result = analyze_fundamental.invoke(
        {
            "financial_data": {
                "AAPL": {
                    "metrics": {
                        "roe": 0.20,
                        "roa": 0.10,
                        "profit_margin": 0.20,
                        "operating_margin": 0.15,
                        "pe_ratio": 10.0,
                        "pb_ratio": 1.0,
                        "ps_ratio": 2.0,
                        "ev_ebitda": 8.0,
                        "debt_to_equity": 0.5,
                        "current_ratio": 2.0,
                        "quick_ratio": 1.5,
                    }
                }
            }
        }
    )["AAPL"]

    assert result["growth"]["status"] == "insufficient_data"
    assert result["overall_score"]["score"] == 100
    assert result["overall_score"]["status"] == "partial"
    assert result["recommendation"] == "strong_buy"


def test_react_empty_fundamentals_return_insufficient_data_not_strong_sell() -> None:
    result = analyze_fundamental.invoke({"financial_data": {"AAPL": {"metrics": {}}}})["AAPL"]

    assert result["overall_score"]["score"] is None
    assert result["overall_score"]["status"] == "insufficient_data"
    assert result["recommendation"] == "insufficient_data"


@pytest.mark.asyncio
async def test_auto_react_tool_does_not_turn_missing_metrics_into_sell(monkeypatch) -> None:
    async def fake_split(_symbol: str):
        return {
            "market_data": {"AAPL": {"current_price": 101.0}},
            "financial_data": {"AAPL": {"metrics": {}}},
            "news_data": [],
        }

    monkeypatch.setattr(auto_tools, "_fetch_and_split", fake_split)

    result = await auto_tools.analyze_fundamental.ainvoke({"symbol": "AAPL"})

    assert result["overall_score"]["status"] == "insufficient_data"
    assert result["recommendation"] == "insufficient_data"
