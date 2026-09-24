"""Tests for the Alpha Vantage snapshot provider (GLOBAL_QUOTE)."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import app.tools.data.fetcher as fetcher


class _FakeResp:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "Global Quote": {
                "01. symbol": "AAPL",
                "05. price": "227.50",
                "06. volume": "45123400",
                "07. latest day": "2026-08-26",
                "08. previous close": "226.10",
                "10. change percent": "0.6192%",
            }
        }


def test_snapshot_maps_quote_fields_into_market_block(monkeypatch) -> None:
    # Hermetic against suite order: a rate-limited response anywhere earlier
    # in the process arms the fetcher's global 60s cooldown and would turn
    # this field-mapping test into a None. The cooldown's behavior is not
    # this test's subject — reset it.
    monkeypatch.setattr(fetcher, "_AV_COOLDOWN_UNTIL", 0.0)
    with patch.object(fetcher.requests, "get", return_value=_FakeResp()):
        result = asyncio.run(fetcher._alphavantage_fetch("AAPL"))

    market = result["market_data"]["AAPL"]
    assert market["current_price"] == 227.50
    assert market["previous_close"] == 226.10
    assert abs(market["change"] - 1.40) < 1e-9
    assert market["change_percent"] == 0.6192
    assert market["volume"] == 45_123_400
    assert market["as_of"] == "2026-08-26"
    assert result["provider"] == "alphavantage"


def test_snapshot_returns_none_without_price() -> None:
    class EmptyResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"Global Quote": {}}

    with patch.object(fetcher.requests, "get", return_value=EmptyResp()):
        assert asyncio.run(fetcher._alphavantage_fetch("AAPL")) is None


def test_provider_is_registered_second_in_the_chain() -> None:
    import inspect

    source = inspect.getsource(fetcher.fetch_stock_data)
    assert '("alphavantage", _alphavantage_fetch)' in source
    assert source.index("alphavantage") < source.index("finnhub")
