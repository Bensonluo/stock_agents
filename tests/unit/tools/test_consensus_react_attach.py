"""Analyst-consensus wiring on the ReAct seam (_fetch_and_split).

The pipeline data agent attaches consensus as its fifth tail gather leg;
this file pins the ReAct twin (_attach_consensus) — both return points of
_fetch_and_split carry the block, 6-digit symbols route to the CN seam
(with the market block's price) while every other symbol routes to the
US ratings seam, and the disabled toggle leaves financial_data untouched.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import get_settings
from app.tools.analysis import auto_tools

_CONSENSUS_BLOCK: dict[str, Any] = {
    "status": "ok",
    "eps_forecast": {"year1": 2026, "eps_mean": 1.53},
}

_US_CONSENSUS_BLOCK: dict[str, Any] = {
    "status": "insufficient_data",
    "ratings": {
        "counts": {"买入": 12, "增持": 8, "中性": 0, "减持": 0, "卖出": 0},
        "dominant": "买入",
        "total": 20,
    },
}


def _consensus_spy(seen: list[tuple[str, float | None]], block: dict[str, Any] | None):
    async def _fake(symbol: str, current_price: float | None = None):
        seen.append((symbol, current_price))
        return block

    return _fake


def _us_consensus_spy(seen: list[str], block: dict[str, Any] | None):
    async def _fake(symbol: str):
        seen.append(symbol)
        return block

    return _fake


def _quiet_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Silence the other tail seams so the tests exercise consensus only."""

    async def _no_bench(ticker: str) -> None:
        return None

    async def _no_cn_bench(symbol: str) -> None:
        return None

    async def _no_news(symbol: str, articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return articles

    monkeypatch.setattr(auto_tools, "fetch_benchmark_history", _no_bench)
    monkeypatch.setattr(auto_tools, "fetch_cn_sector_benchmark", _no_cn_bench)
    monkeypatch.setattr(auto_tools, "_augment_news", _no_news)


@pytest.mark.asyncio
async def test_success_return_attaches_consensus_with_price(monkeypatch) -> None:
    seen: list[tuple[str, float | None]] = []

    async def fake_snapshot(symbol: str) -> dict:
        # Flat provider shape (the _akshare_* contract): market_data IS the
        # block, not keyed by symbol — the keyed alphavantage shape would
        # drive _fetch_and_split into its history-supplement branch.
        return {
            "market_data": {
                "symbol": symbol,
                "current_price": 9.16,
                "historical_data": {"dates": ["2026-01-02"], "close": [9.16]},
            },
            "financial_data": {"metrics": {"pe_ratio": 5.2}},
            "news_data": [],
        }

    monkeypatch.setattr(auto_tools, "fetch_stock_data", fake_snapshot)
    _quiet_tail(monkeypatch)
    monkeypatch.setattr(auto_tools, "fetch_cn_consensus", _consensus_spy(seen, _CONSENSUS_BLOCK))

    data = await auto_tools._fetch_and_split("600000")

    assert seen == [("600000", 9.16)]
    assert data["financial_data"]["600000"]["consensus"] == _CONSENSUS_BLOCK
    # The fetched financials survive beside the annotation.
    assert data["financial_data"]["600000"]["metrics"] == {"pe_ratio": 5.2}


@pytest.mark.asyncio
async def test_history_only_fallback_attaches_consensus(monkeypatch) -> None:
    seen: list[tuple[str, float | None]] = []

    async def dead_snapshot(symbol: str) -> None:
        return None

    async def fake_hist(symbol: str, period: str) -> dict:
        return {
            "dates": ["2026-01-02", "2026-01-03"],
            "open": [9.0, 9.1],
            "high": [9.2, 9.3],
            "low": [8.9, 9.0],
            "close": [9.1, 9.16],
            "volume": [1000, 1100],
        }

    monkeypatch.setattr(auto_tools, "fetch_stock_data", dead_snapshot)
    monkeypatch.setattr(auto_tools, "fetch_historical", fake_hist)
    _quiet_tail(monkeypatch)
    monkeypatch.setattr(auto_tools, "fetch_cn_consensus", _consensus_spy(seen, _CONSENSUS_BLOCK))

    data = await auto_tools._fetch_and_split("600000")

    # Last close is the fallback path's price — the upside math stays honest.
    assert seen == [("600000", 9.16)]
    assert data["financial_data"]["600000"]["consensus"] == _CONSENSUS_BLOCK


@pytest.mark.asyncio
async def test_none_block_leaves_financial_untouched(monkeypatch) -> None:
    seen: list[tuple[str, float | None]] = []

    async def fake_snapshot(symbol: str) -> dict:
        return {
            "market_data": {
                "symbol": symbol,
                "current_price": 9.16,
                "historical_data": {"dates": ["2026-01-02"], "close": [9.16]},
            },
            "financial_data": {"metrics": {"pe_ratio": 5.2}},
            "news_data": [],
        }

    monkeypatch.setattr(auto_tools, "fetch_stock_data", fake_snapshot)
    _quiet_tail(monkeypatch)
    monkeypatch.setattr(auto_tools, "fetch_cn_consensus", _consensus_spy(seen, None))

    data = await auto_tools._fetch_and_split("600000")

    assert seen == [("600000", 9.16)]  # fetched, but no coverage
    assert data["financial_data"]["600000"] == {"metrics": {"pe_ratio": 5.2}}


@pytest.mark.asyncio
async def test_market_dispatch_and_toggle_off_never_fetch(monkeypatch) -> None:
    """6-digit symbols route to the CN seam with the live price; every other
    symbol routes to the US ratings seam (no price argument — the Finnhub
    endpoint carries none); the disabled toggle fetches neither seam."""
    cn_seen: list[tuple[str, float | None]] = []
    us_seen: list[str] = []

    async def fake_snapshot(symbol: str) -> dict:
        return {
            "market_data": {
                "symbol": symbol,
                "current_price": 200.0,
                "historical_data": {"dates": ["2026-01-02"], "close": [200.0]},
            },
            "financial_data": {},
            "news_data": [],
        }

    monkeypatch.setattr(auto_tools, "fetch_stock_data", fake_snapshot)
    _quiet_tail(monkeypatch)
    monkeypatch.setattr(auto_tools, "fetch_cn_consensus", _consensus_spy(cn_seen, _CONSENSUS_BLOCK))
    monkeypatch.setattr(
        auto_tools, "fetch_us_consensus", _us_consensus_spy(us_seen, _US_CONSENSUS_BLOCK)
    )

    data = await auto_tools._fetch_and_split("AAPL")
    assert us_seen == ["AAPL"]  # US symbol → US seam, block attached
    assert cn_seen == []
    assert data["financial_data"]["AAPL"]["consensus"] == _US_CONSENSUS_BLOCK

    data = await auto_tools._fetch_and_split("600000")
    assert cn_seen == [("600000", 200.0)]  # CN symbol → CN seam with price
    assert us_seen == ["AAPL"]  # never routed to the US seam
    assert data["financial_data"]["600000"]["consensus"] == _CONSENSUS_BLOCK

    monkeypatch.setattr(get_settings(), "consensus_enabled", False)
    await auto_tools._fetch_and_split("AAPL")
    await auto_tools._fetch_and_split("600000")
    assert us_seen == ["AAPL"]  # toggle off → neither seam fires
    assert cn_seen == [("600000", 200.0)]
