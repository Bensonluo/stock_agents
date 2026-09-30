"""Analyst-consensus annotation layer for CN symbols (iteration 163).

Two akshare endpoints (1.18.96, shapes verified live 2026-09-30):
    stock_profit_forecast_ths(symbol, indicator='预测年报每股收益')
        [年度, 预测机构数, 最小值, 均值, 最大值, 行业平均数]
    stock_institute_recommend_detail(symbol)
        [股票代码, 股票名称, 目标价, 最新评级, 评级机构, 分析师, 行业, 评级日期]

The annotation is PURE: nothing in the scoring, risk or decision paths may
read it (the liquidity/sector_relative/option_implied convention). The
fetch seam caches the RAW frames for 30 minutes — price-independent — so
the implied upside is recomputed fresh against each caller's price.
"""

from __future__ import annotations

import math
import sys
import types
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.config import get_settings
from app.tools.data.consensus import (
    CONSENSUS_RATING_WINDOW_DAYS,
    MIN_TARGET_OBSERVATIONS,
    consensus_annotation,
    fetch_cn_consensus,
    fetch_us_consensus,
    us_consensus_annotation,
)
from app.tools.data.provider_health import provider_health_snapshot, reset_provider_health

_FORECAST_COLS = ["年度", "预测机构数", "最小值", "均值", "最大值", "行业平均数"]
_RATINGS_COLS = [
    "股票代码",
    "股票名称",
    "目标价",
    "最新评级",
    "评级机构",
    "分析师",
    "行业",
    "评级日期",
]


def _today() -> date:
    return date.today()


def _days_ago(n: int) -> str:
    return (_today() - timedelta(days=n)).isoformat()


def _forecast_df(*rows) -> pd.DataFrame:
    return pd.DataFrame(list(rows), columns=_FORECAST_COLS)


def _ratings_df(*rows) -> pd.DataFrame:
    return pd.DataFrame(list(rows), columns=_RATINGS_COLS)


def _rating_row(target, label, days) -> tuple:
    return ("600000", "浦发银行", target, label, "某证券", "张三", "银行", _days_ago(days))


@pytest.fixture(autouse=True)
def _clear_consensus_cache():
    """Isolation: the shared fetcher cache is module-global (iteration 64)."""
    from app.tools.data import fetcher_common

    prefixes = ("consensus_raw:", "consensus_us_raw:")
    for key in [k for k in fetcher_common._cache if k.startswith(prefixes)]:
        del fetcher_common._cache[key]
    yield


def _install_fake_akshare(
    monkeypatch: pytest.MonkeyPatch,
    calls: list,
    *,
    forecast: pd.DataFrame | None = None,
    ratings: pd.DataFrame | None = None,
    forecast_error: Exception | None = None,
    ratings_error: Exception | None = None,
) -> None:
    fake = types.ModuleType("akshare")

    def _profit_forecast_ths(symbol, indicator="预测年报每股收益"):
        calls.append(("stock_profit_forecast_ths", symbol, indicator))
        if forecast_error is not None:
            raise forecast_error
        return forecast

    def _institute_recommend_detail(symbol):
        calls.append(("stock_institute_recommend_detail", symbol))
        if ratings_error is not None:
            raise ratings_error
        return ratings

    fake.stock_profit_forecast_ths = _profit_forecast_ths
    fake.stock_institute_recommend_detail = _institute_recommend_detail
    monkeypatch.setitem(sys.modules, "akshare", fake)


# --------------------------------------------------------------------------
# Pure layer: consensus_annotation
# --------------------------------------------------------------------------


def test_eps_forecast_two_years_with_growth() -> None:
    """Live 600000 shape: 2026/1.53 (15 orgs, industry 1.86), 2027/1.64."""
    df = _forecast_df(
        (2026, 15, 1.45, 1.53, 1.67, 1.86),
        (2027, 15, 1.55, 1.64, 1.75, 1.95),
        (2028, 14, 1.65, 1.77, 1.90, 2.05),
    )
    block = consensus_annotation(df, None, None)
    assert block is not None and block["status"] == "ok"
    eps = block["eps_forecast"]
    assert eps["year1"] == 2026
    assert eps["eps_mean"] == 1.53
    assert eps["org_count"] == 15
    assert eps["industry_avg"] == 1.86
    assert eps["year2"] == 2027
    assert eps["eps_mean_year2"] == 1.64
    assert eps["implied_growth"] == pytest.approx(0.0719)  # 1.64/1.53 - 1


def test_eps_forecast_single_year_has_no_year2_keys() -> None:
    df = _forecast_df((2026, 15, 1.45, 1.53, 1.67, 1.86))
    eps = consensus_annotation(df, None, None)["eps_forecast"]
    for key in ("year2", "eps_mean_year2", "implied_growth"):
        assert key not in eps


def test_eps_forecast_skips_invalid_rows() -> None:
    """NaN mean and garbage years are not years; a gap means no year2 even
    when later years exist (year2 is strictly year1+1)."""
    df = _forecast_df(
        (2024, 10, 1.0, np.nan, 1.2, 1.4),  # NaN mean → skipped
        ("N/A", 5, 1.0, 1.0, 1.0, 1.0),  # unparseable year → skipped
        (2026, 15, 1.45, 1.53, 1.67, 1.86),
        (2028, 12, 1.6, 1.77, 1.9, 2.0),  # 2027 missing → not year2
    )
    eps = consensus_annotation(df, None, None)["eps_forecast"]
    assert eps["year1"] == 2026
    assert "year2" not in eps


def test_eps_forecast_no_growth_when_mean_nonpositive() -> None:
    df = _forecast_df(
        (2026, 15, 0.0, 0.0, 0.1, 0.5),
        (2027, 15, 0.1, 1.64, 2.0, 1.0),
    )
    eps = consensus_annotation(df, None, None)["eps_forecast"]
    assert eps["year2"] == 2027
    assert "implied_growth" not in eps


def test_eps_forecast_missing_optional_fields_are_none() -> None:
    df = _forecast_df((2026, np.nan, 1.45, 1.53, 1.67, np.nan))
    eps = consensus_annotation(df, None, None)["eps_forecast"]
    assert eps["org_count"] is None
    assert eps["industry_avg"] is None


def test_target_price_stats_over_recent_window() -> None:
    """NaN and stale 目标价 rows are not observations; count/mean/median
    come from the valid recent ones; upside uses the caller's price."""
    df = _ratings_df(
        _rating_row(12.0, "买入", 10),
        _rating_row(8.0, "增持", 5),
        _rating_row(np.nan, "中性", 3),  # missing target → not an observation
        _rating_row(10.0, "买入", 2),
        _rating_row(9.0, "减持", 1),
        _rating_row(100.0, "买入", 400),  # stale → excluded
        _rating_row(50.0, "卖出", 500),  # stale → excluded
    )
    block = consensus_annotation(None, df, 10.0)
    target = block["target_price"]
    assert target["count"] == 4
    assert target["mean"] == pytest.approx(9.75)  # (12+8+10+9)/4
    assert target["median"] == pytest.approx(9.5)  # (9+10)/2
    assert target["window_days"] == CONSENSUS_RATING_WINDOW_DAYS == 180
    assert target["implied_upside"] == pytest.approx(-0.025)  # 9.75/10 - 1


def test_target_price_boundary_180_in_181_out() -> None:
    df = _ratings_df(
        _rating_row(12.0, "买入", 180),  # exactly 180 days old → IN
        _rating_row(8.0, "增持", 10),
        _rating_row(10.0, "中性", 5),
        _rating_row(100.0, "卖出", 181),  # 181 days old → OUT
    )
    target = consensus_annotation(None, df, None)["target_price"]
    assert target["count"] == 3
    assert target["mean"] == pytest.approx(10.0)  # 100.0 must not leak in


def test_target_price_requires_min_observations() -> None:
    assert MIN_TARGET_OBSERVATIONS == 3
    df = _ratings_df(
        _rating_row(12.0, "买入", 10),
        _rating_row(8.0, "增持", 5),
        _rating_row(0.0, "中性", 3),  # non-positive → not an observation
        _rating_row(-5.0, "减持", 2),  # non-positive → not an observation
    )
    block = consensus_annotation(None, df, None)
    assert "target_price" not in block
    # Ratings survive alone — but ratings-only is not enough for "ok".
    assert block["ratings"]["total"] == 4
    assert block["status"] == "insufficient_data"


def test_target_price_no_upside_without_valid_price() -> None:
    df = _ratings_df(
        _rating_row(12.0, "买入", 10),
        _rating_row(8.0, "增持", 5),
        _rating_row(10.0, "中性", 2),
    )
    for price in (None, 0, -3.0, "not-a-number", math.nan):
        target = consensus_annotation(None, df, price)["target_price"]
        assert "implied_upside" not in target


def test_ratings_counts_dominant_and_total() -> None:
    df = _ratings_df(
        _rating_row(14.5, "买入", 10),
        _rating_row(13.0, "买入", 8),
        _rating_row(15.0, "增持", 5),
        _rating_row(12.0, "中性", 2),
        _rating_row(99.0, "买入", 400),  # stale → excluded from counts
    )
    ratings = consensus_annotation(None, df, None)["ratings"]
    assert ratings["counts"] == {"买入": 2, "增持": 1, "中性": 1, "减持": 0, "卖出": 0}
    assert ratings["dominant"] == "买入"
    assert ratings["total"] == 4


def test_ratings_tie_breaks_to_more_bullish() -> None:
    df = _ratings_df(
        _rating_row(14.5, "买入", 10),
        _rating_row(14.5, "买入", 8),
        _rating_row(15.0, "增持", 5),
        _rating_row(15.0, "增持", 2),
    )
    assert consensus_annotation(None, df, None)["ratings"]["dominant"] == "买入"


def test_ratings_unknown_labels_are_ignored() -> None:
    df = _ratings_df(
        _rating_row(14.5, "买入", 10),
        _rating_row(15.0, "推荐", 5),  # off-scale label → ignored
    )
    ratings = consensus_annotation(None, df, None)["ratings"]
    assert ratings["total"] == 1  # known-label recent rows only
    assert ratings["counts"]["买入"] == 1
    assert ratings["dominant"] == "买入"

    unknown_only = _ratings_df(_rating_row(15.0, "推荐", 5))
    annotated = consensus_annotation(unknown_only.assign(目标价=[np.nan]), None, None)
    assert "ratings" not in (annotated or {})


def test_all_inputs_empty_returns_none() -> None:
    assert consensus_annotation(None, None, None) is None
    assert consensus_annotation(_forecast_df(), _ratings_df(), 10.0) is None


def test_eps_only_is_status_ok() -> None:
    df = _forecast_df((2026, 15, 1.45, 1.53, 1.67, 1.86))
    block = consensus_annotation(df, None, None)
    assert block["status"] == "ok"
    assert "target_price" not in block and "ratings" not in block


# --------------------------------------------------------------------------
# Fetch layer: fetch_cn_consensus
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_success_caches_raw_and_recomputes_upside(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One network round-trip per 30-min window; the annotation itself is
    recomputed each call so implied_upside tracks the caller's price."""
    calls: list = []
    forecast = _forecast_df(
        (2026, 15, 1.45, 1.53, 1.67, 1.86),
        (2027, 15, 1.55, 1.64, 1.75, 1.95),
    )
    ratings = _ratings_df(
        _rating_row(12.0, "买入", 10),
        _rating_row(8.0, "增持", 5),
        _rating_row(10.0, "中性", 2),
        _rating_row(9.0, "买入", 1),
    )
    _install_fake_akshare(monkeypatch, calls, forecast=forecast, ratings=ratings)

    first = await fetch_cn_consensus("600000", 10.0)
    assert first is not None and first["status"] == "ok"
    assert first["target_price"]["implied_upside"] == pytest.approx(-0.025)

    second = await fetch_cn_consensus("600000", 9.75)
    assert second["target_price"]["implied_upside"] == pytest.approx(0.0)
    assert second["eps_forecast"]["eps_mean"] == 1.53

    # Raw frames cached — both endpoints hit exactly once for two calls.
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_fetch_total_failure_is_not_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list = []
    reset_provider_health()
    _install_fake_akshare(
        monkeypatch,
        calls,
        forecast_error=Exception("ths down"),
        ratings_error=Exception("sina down"),
    )

    assert await fetch_cn_consensus("600000", 10.0) is None
    assert await fetch_cn_consensus("600000", 10.0) is None
    # Total failure retried — never cached.
    assert len(calls) == 4

    snap = provider_health_snapshot()["providers"]
    assert snap["ths-forecast"]["fail"] == 2
    assert snap["sina-ratings"]["fail"] == 2


@pytest.mark.asyncio
async def test_fetch_partial_forecast_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []
    reset_provider_health()
    ratings = _ratings_df(
        _rating_row(12.0, "买入", 10),
        _rating_row(8.0, "增持", 5),
        _rating_row(10.0, "中性", 2),
    )
    _install_fake_akshare(monkeypatch, calls, forecast_error=Exception("ths down"), ratings=ratings)

    block = await fetch_cn_consensus("600000", 8.0)
    assert block is not None and block["status"] == "ok"
    assert "eps_forecast" not in block
    assert block["target_price"]["implied_upside"] == pytest.approx(0.25)  # 10/8 - 1

    snap = provider_health_snapshot()["providers"]
    assert snap["ths-forecast"]["fail"] == 1
    assert snap["sina-ratings"]["ok"] == 1


@pytest.mark.asyncio
async def test_fetch_without_akshare_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "akshare", None)  # import akshare → ImportError
    reset_provider_health()
    assert await fetch_cn_consensus("600000", 10.0) is None
    assert provider_health_snapshot()["providers"] == {}


@pytest.mark.asyncio
async def test_fetch_empty_frames_are_cached_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty frame is a valid provider answer (no coverage), not a
    failure: it caches like a success so uncovered symbols don't hammer
    the endpoints every run."""
    calls: list = []
    reset_provider_health()
    _install_fake_akshare(monkeypatch, calls, forecast=_forecast_df(), ratings=_ratings_df())

    assert await fetch_cn_consensus("600000", 10.0) is None
    assert await fetch_cn_consensus("600000", 10.0) is None
    assert len(calls) == 2  # second call served from the raw cache

    snap = provider_health_snapshot()["providers"]
    assert snap["ths-forecast"]["ok"] == 1
    assert snap["sina-ratings"]["ok"] == 1


# --------------------------------------------------------------------------
# US twin (iteration 167): us_consensus_annotation / fetch_us_consensus
# --------------------------------------------------------------------------


def _us_items(period: str = "2026-09-01", **bands: int) -> dict:
    """One Finnhub /stock/recommendation snapshot row."""
    row = {
        "period": period,
        "strongBuy": 0,
        "buy": 0,
        "hold": 0,
        "sell": 0,
        "strongSell": 0,
        "symbol": "AAPL",
    }
    row.update(bands)
    return row


def test_us_annotation_maps_five_bands() -> None:
    """Full-band payload: counts land on the canonical CN scale, ratings-only
    never claims "ok" (the endpoint has no hard-number evidence), and no
    unconsumed keys ride along on the block."""
    block = us_consensus_annotation([_us_items(strongBuy=12, buy=8, hold=3, sell=1)])
    assert block is not None
    assert block["status"] == "insufficient_data"
    assert block["ratings"]["counts"] == {
        "买入": 12,
        "增持": 8,
        "中性": 3,
        "减持": 1,
        "卖出": 0,
    }
    assert block["ratings"]["dominant"] == "买入"
    assert block["ratings"]["total"] == 24
    assert set(block) == {"status", "ratings"}


def test_us_annotation_latest_period_wins_regardless_of_order() -> None:
    """Finnhub returns monthly snapshots latest-first, but the pure layer
    must not rely on that ordering — the max period string wins."""
    block = us_consensus_annotation(
        [
            _us_items("2026-07-01", buy=2),
            _us_items("2026-09-01", buy=7, hold=5, sell=5, strongSell=3),
            _us_items("2026-08-01", buy=1),
        ]
    )
    assert block is not None
    assert block["ratings"]["total"] == 20
    assert block["ratings"]["counts"]["增持"] == 7  # buy band of the 09-01 snapshot


def test_us_annotation_tie_breaks_to_more_bullish() -> None:
    block = us_consensus_annotation([_us_items(buy=5, sell=5)])
    assert block is not None
    assert block["ratings"]["dominant"] == "增持"


def test_us_annotation_rejects_non_list_or_empty_inputs() -> None:
    assert us_consensus_annotation([]) is None
    assert us_consensus_annotation({"not": "a list"}) is None
    assert us_consensus_annotation(None) is None


def test_us_annotation_rejects_all_zero_or_bandless_rows() -> None:
    assert us_consensus_annotation([_us_items()]) is None  # all-zero bands
    assert us_consensus_annotation([{"period": "2026-09-01", "symbol": "AAPL"}]) is None


def test_us_annotation_filters_non_dict_rows() -> None:
    block = us_consensus_annotation(["garbage", None, _us_items(buy=2)])
    assert block is not None
    assert block["ratings"]["total"] == 2


@pytest.mark.asyncio
async def test_us_fetch_success_caches_raw(monkeypatch: pytest.MonkeyPatch) -> None:
    """One Finnhub round-trip per 30-min window; both calls return the same
    annotation from the cached raw snapshots."""
    calls: list = []
    reset_provider_health()

    def _fake_get(path, params):
        calls.append((path, params))
        return [_us_items(strongBuy=12, buy=8)]

    monkeypatch.setattr(get_settings(), "finnhub_api_key", "test-key")
    monkeypatch.setattr("app.tools.data.consensus._finnhub_get", _fake_get)

    first = await fetch_us_consensus("AAPL")
    assert first is not None
    assert first["ratings"]["total"] == 20
    second = await fetch_us_consensus("AAPL")
    assert second == first
    assert calls == [("/stock/recommendation", {"symbol": "AAPL"})]

    snap = provider_health_snapshot()["providers"]
    assert snap["finnhub-recommendation"]["ok"] == 1
    assert snap["finnhub-recommendation"]["fail"] == 0


@pytest.mark.asyncio
async def test_us_fetch_total_failure_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []
    reset_provider_health()

    def _fake_get(path, params):
        calls.append((path, params))
        return None

    monkeypatch.setattr(get_settings(), "finnhub_api_key", "test-key")
    monkeypatch.setattr("app.tools.data.consensus._finnhub_get", _fake_get)

    assert await fetch_us_consensus("AAPL") is None
    assert await fetch_us_consensus("AAPL") is None
    assert len(calls) == 2  # failure retried, never cached

    snap = provider_health_snapshot()["providers"]
    assert snap["finnhub-recommendation"]["fail"] == 2


@pytest.mark.asyncio
async def test_us_fetch_empty_list_is_cached_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """No coverage is a valid provider answer (thin coverage, non-US
    listings): the empty list caches like a success so the endpoint is
    not re-hit on every call."""
    calls: list = []
    reset_provider_health()

    def _fake_get(path, params):
        calls.append((path, params))
        return []

    monkeypatch.setattr(get_settings(), "finnhub_api_key", "test-key")
    monkeypatch.setattr("app.tools.data.consensus._finnhub_get", _fake_get)

    assert await fetch_us_consensus("0700.HK") is None
    assert await fetch_us_consensus("0700.HK") is None
    assert len(calls) == 1  # second call served from the raw cache

    snap = provider_health_snapshot()["providers"]
    assert snap["finnhub-recommendation"]["ok"] == 1


@pytest.mark.asyncio
async def test_us_fetch_keyless_never_records(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keyless is a configuration state, not a provider failure — the seam
    returns None without a network call and without recording (the
    iteration 104 keyless convention)."""
    reset_provider_health()
    monkeypatch.setattr(get_settings(), "finnhub_api_key", None)

    assert await fetch_us_consensus("AAPL") is None
    assert provider_health_snapshot()["providers"] == {}
