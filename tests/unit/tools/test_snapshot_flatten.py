"""Boundary contract of the snapshot flatten seam.

``fetch_stock_data`` normalizes every provider result — keyed
(tencent-hk/eastmoney-hk/alphavantage/akshare) or flat (yfinance/finnhub) —
to the FLAT snapshot shape (``market_data`` IS the block, ``"symbol"``
injected as a string value) before returning and caching it. These pins lock
that boundary directly: the helpers had zero coverage, which is how a keyed
read downstream (the data_agent fallback) survived unnoticed.

Consumers of a ``fetch_stock_data`` result must read the block flat —
``market_data[symbol]`` is the *pipeline state* convention, never the
result convention.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.tools.data import fetcher as fetcher_mod
from app.tools.data.fetcher_common import _flatten_snapshot, _snapshot_has_price


@pytest.fixture(autouse=True)
def _clear_caches():
    fetcher_mod._cache.clear()
    yield
    fetcher_mod._cache.clear()


_KEYED: dict[str, Any] = {
    "market_data": {
        "TEST": {
            "current_price": 9.16,
            "historical_data": {"dates": ["2026-01-02"], "close": [9.16]},
        }
    },
    "financial_data": {"metrics": {"pe_ratio": 5.2}},
    "news_data": [{"title": "t"}],
}


class TestFlattenSnapshot:
    def test_keyed_provider_result_flattens_with_symbol_injected(self) -> None:
        flat = _flatten_snapshot(_KEYED, "TEST")

        assert flat["market_data"] == {
            "current_price": 9.16,
            "historical_data": {"dates": ["2026-01-02"], "close": [9.16]},
            "symbol": "TEST",  # injected string value, not a keyed nest
        }
        assert flat["financial_data"] == {"metrics": {"pe_ratio": 5.2}}
        assert flat["news_data"] == [{"title": "t"}]

    def test_flat_provider_result_passes_through_unchanged(self) -> None:
        flat_in = {
            "market_data": {
                "symbol": "TEST",
                "current_price": 3.0,
                "historical_data": {"close": [3.0]},
            },
            "financial_data": {},
            "news_data": [],
        }

        out = _flatten_snapshot(flat_in, "TEST")

        assert out is flat_in  # already flat: returned as-is, never re-wrapped

    def test_snapshot_has_price_accepts_both_shapes_and_rejects_priceless(self) -> None:
        assert _snapshot_has_price({"market_data": {"current_price": 9.0}})
        assert _snapshot_has_price({"market_data": {"TEST": {"current_price": 9.0}}})
        # A price keyed under anything else — including the injected symbol
        # string — does not count as a flat price.
        assert not _snapshot_has_price({"market_data": {"TEST": {}}})
        assert not _snapshot_has_price({"market_data": {}})
        assert not _snapshot_has_price({})
        assert not _snapshot_has_price({"market_data": "garbage"})


@pytest.mark.asyncio
async def test_provider_chain_returns_flat_and_caches_flat(monkeypatch) -> None:
    """End-to-end through fetch_stock_data: a keyed provider's result comes
    back flat (symbol injected) and the cache stores the flat block."""

    async def _dead_yfinance(symbol: str) -> None:
        return None

    tail = AsyncMock(return_value=None)
    monkeypatch.setattr(fetcher_mod, "_yfinance_fetch", _dead_yfinance)
    monkeypatch.setattr(fetcher_mod, "_alphavantage_fetch", AsyncMock(return_value=_KEYED))
    monkeypatch.setattr(fetcher_mod, "_finnhub_fetch", tail)
    monkeypatch.setattr(fetcher_mod, "_akshare_fetch", tail)
    monkeypatch.setattr(fetcher_mod, "_yahoo_api_fetch", tail)

    result = await fetcher_mod.fetch_stock_data("TEST")

    assert result is not None
    market = result["market_data"]
    assert market["current_price"] == 9.16
    assert market["symbol"] == "TEST"
    assert "TEST" not in market  # the keyed nesting is gone at the boundary
    assert result["financial_data"] == {"metrics": {"pe_ratio": 5.2}}

    cached = fetcher_mod._cache_get("stock_TEST")
    assert cached is not None
    assert cached["market_data"]["symbol"] == "TEST"  # cache stores the FLAT block

    tail.assert_not_awaited()  # alphavantage's success stops the chain
