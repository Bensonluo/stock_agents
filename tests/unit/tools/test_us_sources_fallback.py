"""US data-source fallbacks: Sina history + Finnhub news + stooq suffix.

The Tencent Cloud deploy (verified live 2026-09-25, in the production
container) is rate-limited by Yahoo on every endpoint AND has East Money's
US kline/list endpoints connection-dropped — so the old US fallbacks were
structurally dead: `ak.stock_us_hist` with a bare ticker never worked (the
endpoint expects market-prefixed codes like 105.MSFT), and stooq was
queried without the `.us` suffix US tickers require. Sina (`stock_us_daily`,
plain ticker) is the one US history source that answers from that host.

These tests pin the three fixes offline with a fake akshare module:
the Sina seam's window slice and canonical shape, the snapshot provider's
derived market_data, and the stooq URL contract.
"""

from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import pytest

import app.tools.data.fetcher as fetcher_mod
from app.config import get_settings
from app.tools.data.fetcher import (
    _akshare_us,
    _sina_us_hist,
    fetch_historical,
    fetch_us_news,
    finnhub_news_articles,
)

pytestmark = pytest.mark.asyncio


def _bars(first: str, last: str, step_days: int = 5) -> pd.DataFrame:
    """Daily-ish bars from `first` to `last` (inclusive), simple uptrend."""
    d0 = datetime.strptime(first, "%Y-%m-%d")
    d1 = datetime.strptime(last, "%Y-%m-%d")
    rows = []
    price = 100.0
    day = d0
    while day <= d1:
        rows.append(
            {
                "date": day.strftime("%Y-%m-%d"),
                "open": price,
                "high": price + 1.0,
                "low": price - 1.0,
                "close": price + 0.5,
                "volume": 1_000_000.0,
            }
        )
        price += 1.0
        day += timedelta(days=step_days)
    return pd.DataFrame(rows)


def _fake_akshare_module(hist_df: pd.DataFrame | None) -> types.ModuleType:
    mod = types.ModuleType("akshare")

    def stock_us_daily(symbol: str, adjust: str = "") -> pd.DataFrame | None:
        assert adjust == "qfq"
        return hist_df

    mod.stock_us_daily = stock_us_daily  # type: ignore[attr-defined]
    return mod


@pytest.fixture(autouse=True)
def _clear_caches():
    fetcher_mod._cache.clear()
    yield
    fetcher_mod._cache.clear()


@pytest.fixture(autouse=True)
def _no_third_party_keys(monkeypatch: pytest.MonkeyPatch):
    """Tests must not depend on (or fire) real Finnhub/AlphaVantage keys."""
    settings = get_settings()
    monkeypatch.setattr(settings, "finnhub_api_key", None)
    monkeypatch.setattr(settings, "alpha_vantage_key", None)


async def test_sina_us_hist_slices_window_and_normalizes() -> None:
    """Full Sina history is sliced to the requested window; keys canonical."""
    recent = datetime.now().strftime("%Y-%m-%d")
    three_years_ago = (datetime.now() - timedelta(days=3 * 365)).strftime("%Y-%m-%d")
    df = pd.concat([_bars(three_years_ago, three_years_ago), _bars(recent, recent)])
    monkeypatch_holder = pytest.MonkeyPatch()
    monkeypatch_holder.setitem(sys.modules, "akshare", _fake_akshare_module(df))
    try:
        result = await _sina_us_hist("MSFT", "1y")
    finally:
        monkeypatch_holder.undo()

    assert result is not None
    assert set(result) == {"dates", "open", "high", "low", "close", "volume"}
    assert result["dates"] == [recent]  # the 3y-ago bar is outside the window
    assert result["close"] == [100.5]


async def test_sina_us_hist_empty_history_returns_none() -> None:
    monkeypatch_holder = pytest.MonkeyPatch()
    monkeypatch_holder.setitem(sys.modules, "akshare", _fake_akshare_module(None))
    try:
        assert await _sina_us_hist("BOGUS", "1y") is None
    finally:
        monkeypatch_holder.undo()


async def test_fetch_historical_us_uses_sina_when_yahoo_dead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Yahoo 429 → the chain must land on Sina and return usable bars."""

    class _DeadYf:
        @staticmethod
        def Ticker(symbol: str):  # noqa: N802 - yfinance API shape
            raise RuntimeError("Too Many Requests")

    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    df = _bars((datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d"), yesterday)

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=_DeadYf.Ticker))
    monkeypatch.setitem(sys.modules, "akshare", _fake_akshare_module(df))

    result = await fetch_historical("AAPL", "1mo")

    assert result is not None
    assert result["symbol"] == "AAPL"
    assert result["dates"]  # bars made it through
    assert set(result) >= {"dates", "open", "high", "low", "close", "volume"}
    # Window discipline: nothing older than the requested month.
    cutoff = (datetime.now() - timedelta(days=31)).strftime("%Y-%m-%d")
    assert result["dates"][0] >= cutoff


async def test_akshare_us_snapshot_from_sina(monkeypatch: pytest.MonkeyPatch) -> None:
    """The provider emits a snapshot with price/change/USD off Sina bars."""

    class _FakeAk:
        @staticmethod
        def stock_us_valuation_baidu(**kwargs: Any) -> pd.DataFrame:
            raise RuntimeError("baidu guguang unreachable from container")

    recent = datetime.now().strftime("%Y-%m-%d")
    df = _bars((datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d"), recent)
    monkeypatch.setitem(sys.modules, "akshare", _fake_akshare_module(df))

    result = await _akshare_us("AAPL", _FakeAk())

    assert result is not None
    market = result["market_data"]
    assert market["currency"] == "USD"
    assert market["current_price"] == pytest.approx(df["close"].iloc[-1])
    assert market["previous_close"] == pytest.approx(df["close"].iloc[-2])
    assert market["change_percent"] == pytest.approx(
        (df["close"].iloc[-1] - df["close"].iloc[-2]) / df["close"].iloc[-2] * 100
    )
    assert market["historical_data"]["dates"]
    # Dead valuation feed degrades to the empty-metrics contract.
    assert result["financial_data"] == {"metrics": {}}


async def test_stooq_us_symbol_carries_us_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    """US tickers must query stooq as `aapl.us` — the bare form returns an
    empty CSV and the whole last-resort layer silently no-ops."""

    class _DeadYf:
        @staticmethod
        def Ticker(symbol: str):  # noqa: N802
            raise RuntimeError("Too Many Requests")

    urls: list[str] = []

    class _Resp:
        text = "Date,Open,High,Low,Close,Volume\n2026-09-24,100,101,99,100.5,1000\n"

        def raise_for_status(self) -> None:
            return None

    def _fake_get(url: str, **kwargs: Any) -> _Resp:
        urls.append(url)
        return _Resp()

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=_DeadYf.Ticker))
    # Sina has nothing for this symbol → chain falls through to yahoo-api
    # and stooq, both routed through the patched requests.get.
    monkeypatch.setitem(sys.modules, "akshare", _fake_akshare_module(None))
    monkeypatch.setattr(fetcher_mod.requests, "get", _fake_get)

    result = await fetch_historical("AAPL", "1mo")

    stooq_urls = [u for u in urls if "stooq.com" in u]
    assert stooq_urls and "aapl.us" in stooq_urls[0]
    assert result is not None and result["dates"] == ["2026-09-24"]


async def test_fetch_us_news_without_key_returns_empty() -> None:
    """No FINNHUB_API_KEY → [] (empty-feed behavior, never an exception)."""
    assert await fetch_us_news("AAPL") == []


async def test_finnhub_news_articles_stamp_symbol_attribution() -> None:
    """Finnhub articles must carry original_symbol/related_symbols when the
    queried symbol is known — sentiment's per-symbol matching keys off those
    fields, and unattributed fallback news starves every symbol but the
    first (review 2026-09-26, P2#7)."""
    items = [{"headline": "Apple profit rises", "url": "https://x/1", "datetime": 1, "source": "R"}]
    stamped = finnhub_news_articles(items, symbol="AAPL")
    assert stamped[0]["original_symbol"] == "AAPL"
    assert stamped[0]["related_symbols"] == ["AAPL"]
    # Without a symbol the canonical five-key shape stays unchanged.
    plain = finnhub_news_articles(items)
    assert "original_symbol" not in plain[0]
    assert "related_symbols" not in plain[0]


async def test_fetch_us_news_articles_carry_symbol_attribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The provider seam end to end: key set + fake /company-news → every
    returned article is attributed to the queried symbol."""
    settings = get_settings()
    monkeypatch.setattr(settings, "finnhub_api_key", "test-key")
    items = [
        {"headline": f"Apple story {i}", "url": f"https://x/{i}", "datetime": 1, "source": "R"}
        for i in range(3)
    ]
    monkeypatch.setattr(fetcher_mod, "_finnhub_get", lambda path, params: items)
    articles = await fetch_us_news("AAPL")
    assert len(articles) == 3
    assert all(
        a["original_symbol"] == "AAPL" and a["related_symbols"] == ["AAPL"] for a in articles
    )
