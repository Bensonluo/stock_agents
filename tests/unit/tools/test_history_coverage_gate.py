"""Coverage gate for capped history providers (Alpha Vantage free tier).

First empirical walk-forward run (2026-09-25) exposed the seam: AV's free
tier caps TIME_SERIES_DAILY at the most recent ~100 entries, and its thin
"success" terminated the provider chain before the multi-year sources
(AkShare for CN, Sina for US) ever ran — ``fetch_historical(period="3y")``
silently returned 100 bars, and the walk-forward died with "not enough
data for one train+test window". The gate: an AV response that cannot
cover a fair share of the requested window falls through to the next
provider instead of ending the chain.
"""

from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta

import pandas as pd
import pytest

import app.tools.data.fetcher as fetcher_mod
from app.config import get_settings
from app.tools.data.fetcher import _history_covers_period, fetch_historical


def _thin_av_payload(n_bars: int = 100, step_days: int = 1) -> dict:
    """AV-shaped payload: the most recent ``n_bars`` entries, ~daily spacing."""
    last = datetime.now() - timedelta(days=1)
    dates = [(last - timedelta(days=step_days * i)).strftime("%Y-%m-%d") for i in range(n_bars)]
    return {
        "dates": list(reversed(dates)),
        "open": [10.0] * n_bars,
        "high": [11.0] * n_bars,
        "low": [9.0] * n_bars,
        "close": [10.5] * n_bars,
        "volume": [1_000_000.0] * n_bars,
    }


def _cn_akshare_frame(n_bars: int = 730, step_days: int = 2) -> pd.DataFrame:
    """CN-shaped East Money frame (multi-year span, Chinese column names)."""
    last = datetime.now() - timedelta(days=1)
    rows = []
    for i in range(n_bars):
        day = last - timedelta(days=step_days * (n_bars - 1 - i))
        rows.append(
            {
                "日期": day.strftime("%Y-%m-%d"),
                "开盘": 10.0,
                "收盘": 10.5,
                "最高": 11.0,
                "最低": 9.0,
                "成交量": 1_000_000.0,
            }
        )
    return pd.DataFrame(rows)


def _fake_akshare_module(cn_df: pd.DataFrame | None, *, must_not_run: bool = False):
    mod = types.ModuleType("akshare")

    def stock_zh_a_hist(symbol, period, start_date, end_date, adjust):
        assert not must_not_run, "akshare must not be reached in this scenario"
        assert adjust == "qfq"
        return cn_df

    mod.stock_zh_a_hist = stock_zh_a_hist  # type: ignore[attr-defined]
    return mod


class _DeadYf:
    @staticmethod
    def Ticker(symbol: str):  # noqa: N802 - yfinance API shape
        raise RuntimeError("Too Many Requests")


@pytest.fixture(autouse=True)
def _clear_caches():
    fetcher_mod._cache.clear()
    yield
    fetcher_mod._cache.clear()


@pytest.fixture(autouse=True)
def _key_state(monkeypatch: pytest.MonkeyPatch):
    """Finnhub stays out of the picture; the AV key is present (the bug needs it)."""
    settings = get_settings()
    monkeypatch.setattr(settings, "finnhub_api_key", None)
    monkeypatch.setattr(settings, "alpha_vantage_key", "TEST_AV_KEY")


def test_history_covers_period_math() -> None:
    """Span math: half of the requested window is the acceptance line."""
    ok = _thin_av_payload(n_bars=60, step_days=10)  # span ≈ 600d ≥ 0.5×1095
    assert _history_covers_period(ok, "3y") is True
    thin = _thin_av_payload()  # span ≈ 100d ≪ 0.5×1095
    assert _history_covers_period(thin, "3y") is False
    assert _history_covers_period(thin, "1mo") is True  # 100d ≫ 0.5×30
    assert _history_covers_period({"dates": []}, "3y") is False
    assert _history_covers_period({"dates": ["2026-09-01"]}, "3y") is False
    assert _history_covers_period({"dates": ["garbage", "2026-09-24"]}, "3y") is False


@pytest.mark.asyncio
async def test_thin_av_response_falls_through_to_akshare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bug: AV's 100-bar slice terminated the chain for a 3y request —
    the walk-forward then starved. It must fall through to AkShare."""

    async def _fake_av(symbol: str, period: str) -> dict:
        return _thin_av_payload()

    monkeypatch.setattr(fetcher_mod, "_alphavantage_historical", _fake_av)
    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=_DeadYf.Ticker))
    monkeypatch.setitem(sys.modules, "akshare", _fake_akshare_module(_cn_akshare_frame(n_bars=730)))

    result = await fetch_historical("600000", "3y")

    assert result is not None
    assert len(result["dates"]) == 730  # AkShare bars, not AV's 100
    assert result["symbol"] == "600000"


@pytest.mark.asyncio
async def test_covering_av_response_short_period_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Short requests the AV cap can legitimately serve stay served by AV —
    the gate must not push every request down the (slower) chain."""
    av_payload = _thin_av_payload(n_bars=20, step_days=1)  # spans ~20d ≥ 0.5×30

    async def _fake_av(symbol: str, period: str) -> dict:
        return av_payload

    monkeypatch.setattr(fetcher_mod, "_alphavantage_historical", _fake_av)
    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=_DeadYf.Ticker))
    monkeypatch.setitem(sys.modules, "akshare", _fake_akshare_module(None, must_not_run=True))

    result = await fetch_historical("600000", "1mo")

    assert result is not None
    assert len(result["dates"]) == 20
