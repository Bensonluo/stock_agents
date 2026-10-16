"""Analyst-depth annotations the data agent derives from already-fetched
payloads (audit 2026-09-30: Yahoo's aggregated analyst targets were inside
every US/HK ``ticker.info`` download and never mapped; the EPS surprise
history was downloaded every run and ignored).

Two seams, both zero-network and pure at the mapping layer:

    info_consensus_annotation  — ticker.info → the consensus record shape the
                                 CN THS/Sina seam already emits (no new
                                 schema); non-CN symbols only, so the richer
                                 CN block keeps precedence structurally.
    earnings_surprise_summary  — canonical earnings records → compact
                                 most-recent-first surprise history (max 4,
                                 reported quarters only).

Wiring pins: the financial leg stages the info draft for US/HK only, the
execute-level tail merge lets the fetched Finnhub block win per sub-block
while the draft's target_price fills the ratings-only gap, and a CN symbol's
fetched block is never touched by any of it.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd
import pytest

import app.agents.data_agent as data_agent_mod
from app.config import get_settings
from app.tools.data.consensus import info_consensus_annotation
from app.tools.data.fetcher import earnings_surprise_summary

# --------------------------------------------------------------------------
# Pure layer: info_consensus_annotation
# --------------------------------------------------------------------------


def _full_us_info() -> dict[str, Any]:
    return {
        "currentPrice": 200.0,
        "targetMeanPrice": 250.0,
        "targetMedianPrice": 245.0,
        "targetLowPrice": 180.0,
        "targetHighPrice": 300.0,
        "numberOfAnalystOpinions": 25,
        "recommendationKey": "buy",
        "recommendationMean": 2.1,
    }


def test_full_us_info_maps_targets_onto_the_existing_shape() -> None:
    block = info_consensus_annotation(_full_us_info())

    assert block is not None
    assert block["status"] == "ok"
    assert block["target_price"] == {
        "count": 25,
        "mean": 250.0,
        "median": 245.0,
        "low": 180.0,
        "high": 300.0,
        "implied_upside": 0.25,  # 250/200 - 1, the CN block's own math
    }
    # The info source carries no per-band counts — the canonical five-key
    # dict stays at zero (no fabricated observations); the provider's own
    # aggregate summary holds the real evidence.
    assert block["ratings"] == {
        "counts": {"买入": 0, "增持": 0, "中性": 0, "减持": 0, "卖出": 0},
        "dominant": "buy",
        "mean": 2.1,
        "total": 25,
    }


def test_info_block_is_json_safe_with_numpy_inputs() -> None:
    info = {
        "currentPrice": np.float64(200.0),
        "targetMeanPrice": np.float64(250.0),
        "targetMedianPrice": np.float64(245.0),
        "numberOfAnalystOpinions": np.int64(25),
        "recommendationMean": np.float64(2.1),
    }

    block = info_consensus_annotation(info)

    assert block is not None
    assert json.loads(json.dumps(block)) == block
    assert isinstance(block["target_price"]["mean"], float)
    assert isinstance(block["target_price"]["count"], int)


def test_mean_only_info_omits_absent_fields() -> None:
    """Only set fields that actually exist in info — a bare mean emits no
    count/median/low/high keys and no ratings block."""
    block = info_consensus_annotation({"targetMeanPrice": 12.5})

    assert block is not None
    assert block["status"] == "ok"
    assert block["target_price"] == {"mean": 12.5}
    assert "ratings" not in block


def test_ratings_only_info_is_insufficient_data() -> None:
    block = info_consensus_annotation({"recommendationKey": "hold", "recommendationMean": 3.0})

    assert block is not None
    assert block["status"] == "insufficient_data"
    assert "target_price" not in block
    assert block["ratings"]["dominant"] == "hold"


def test_dominant_buckets_from_mean_when_key_string_missing() -> None:
    """Yahoo's 1-5 mean shares the canonical scale's polarity (1=strong buy);
    nearest label wins when the provider key string is absent."""
    assert info_consensus_annotation({"recommendationMean": 1.4})["ratings"]["dominant"] == "买入"
    assert info_consensus_annotation({"recommendationMean": 2.4})["ratings"]["dominant"] == "增持"
    assert info_consensus_annotation({"recommendationMean": 4.6})["ratings"]["dominant"] == "卖出"


def test_nonpositive_and_garbage_fields_degrade_to_absence() -> None:
    assert info_consensus_annotation({}) is None
    assert info_consensus_annotation({"targetMeanPrice": 0}) is None
    assert info_consensus_annotation({"targetMeanPrice": -5.0}) is None
    assert info_consensus_annotation({"targetMeanPrice": float("nan")}) is None
    assert info_consensus_annotation({"targetMeanPrice": "not-a-number"}) is None
    assert info_consensus_annotation({"recommendationMean": 0}) is None  # off-scale
    assert info_consensus_annotation(None) is None
    assert info_consensus_annotation(["not", "a", "dict"]) is None


def test_implied_upside_falls_back_to_regular_market_price() -> None:
    block = info_consensus_annotation({"targetMeanPrice": 110.0, "regularMarketPrice": 100.0})
    assert block is not None
    assert block["target_price"]["implied_upside"] == pytest.approx(0.10)

    # No price anywhere → the optional upside key is simply absent.
    no_price = info_consensus_annotation({"targetMeanPrice": 110.0})
    assert no_price is not None
    assert "implied_upside" not in no_price["target_price"]


# --------------------------------------------------------------------------
# Pure layer: earnings_surprise_summary
# --------------------------------------------------------------------------


def _record(date: str, estimate: float | None, actual: float | None, pct: float | None):
    return {"date": date, "eps_estimate": estimate, "eps_actual": actual, "surprise_pct": pct}


def test_summary_sorts_most_recent_first_and_caps_at_four() -> None:
    records = [
        _record("2025-03-31", 1.20, 1.25, 4.1),
        _record("2025-12-31", 1.05, 0.90, -14.3),
        _record("2024-12-31", 0.80, 0.82, 2.5),
        _record("2025-09-30", 1.10, 1.14, 3.6),
        _record("2024-09-30", 0.75, 0.70, -6.7),
        _record("2025-06-30", 1.35, 1.30, -3.7),
    ]

    summary = earnings_surprise_summary(records)

    assert summary == {
        "last_4": [
            {"date": "2025-12-31", "estimate": 1.05, "actual": 0.90, "surprise_pct": -14.3},
            {"date": "2025-09-30", "estimate": 1.10, "actual": 1.14, "surprise_pct": 3.6},
            {"date": "2025-06-30", "estimate": 1.35, "actual": 1.30, "surprise_pct": -3.7},
            {"date": "2025-03-31", "estimate": 1.20, "actual": 1.25, "surprise_pct": 4.1},
        ]
    }


def test_summary_keeps_only_reported_quarters() -> None:
    """Future scheduled quarters carry an estimate but no actual — not a
    surprise, so they never enter the history."""
    records = [
        _record("2026-06-30", 1.50, None, None),
        _record("2026-03-31", 1.40, None, None),
        _record("2025-12-31", 1.05, 0.90, -14.3),
    ]

    summary = earnings_surprise_summary(records)

    assert summary is not None
    assert [row["date"] for row in summary["last_4"]] == ["2025-12-31"]
    assert summary["last_4"][0]["estimate"] == 1.05


def test_summary_is_none_without_any_reported_quarters() -> None:
    assert earnings_surprise_summary([]) is None
    assert earnings_surprise_summary(None) is None
    assert earnings_surprise_summary([_record("2026-06-30", 1.5, None, None)]) is None


# --------------------------------------------------------------------------
# Wiring: the financial leg stages both annotations
# --------------------------------------------------------------------------


class _FakeTicker:
    def __init__(
        self,
        info: dict,
        earnings_dates: Any = None,
        quarterly_frames: dict[str, pd.DataFrame | None] | None = None,
    ):
        self.info = info
        self.income_stmt = pd.DataFrame()
        self.balance_sheet = pd.DataFrame()
        self.cashflow = pd.DataFrame()
        self.earnings_dates = earnings_dates
        # Trend depth: real yfinance exposes these three aliases off the
        # same session; None mirrors a rate-limited/absent statement.
        frames = quarterly_frames or {}
        self.quarterly_income_stmt = frames.get("income")
        self.quarterly_balance_sheet = frames.get("balance")
        self.quarterly_cashflow = frames.get("cash")


def _financial_fetch(monkeypatch: pytest.MonkeyPatch, ticker: _FakeTicker) -> dict[str, Any]:
    monkeypatch.setattr(data_agent_mod.yf, "Ticker", lambda _symbol: ticker)
    return data_agent_mod._sync_fetch_financial_data("AAPL", "AAPL", lambda _df: {})


def test_us_financial_fetch_attaches_info_consensus(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _financial_fetch(monkeypatch, _FakeTicker(_full_us_info()))

    assert result["consensus"]["target_price"]["mean"] == 250.0
    assert result["consensus"]["ratings"]["dominant"] == "buy"


def test_hk_symbol_also_gets_the_info_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    """HK rides the non-CN seam in the tail gather, so the draft applies —
    Finnhub carries no HK coverage and Yahoo's info is the only source."""
    monkeypatch.setattr(data_agent_mod.yf, "Ticker", lambda _symbol: _FakeTicker(_full_us_info()))

    result = data_agent_mod._sync_fetch_financial_data("3690.HK", "3690.HK", lambda _df: {})

    assert result["consensus"]["status"] == "ok"


def test_cn_symbol_never_stages_the_info_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    """CN precedence is structural: the same Yahoo-rich info produces NO
    draft for a 6-digit symbol — the tail gather's THS/Sina block is the
    only writer, so there is nothing for the draft to clobber."""
    monkeypatch.setattr(data_agent_mod.yf, "Ticker", lambda _symbol: _FakeTicker(_full_us_info()))

    result = data_agent_mod._sync_fetch_financial_data("600000", "600000", lambda _df: {})

    assert "consensus" not in result


def test_consensus_toggle_off_keeps_the_draft_dark(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "consensus_enabled", False)

    result = _financial_fetch(monkeypatch, _FakeTicker(_full_us_info()))

    assert "consensus" not in result


def test_earnings_surprise_rides_the_financial_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real yfinance alias columns, deliberately oldest-first: the summary
    must sort by date, not trust frame order, and drop unreported quarters."""
    frame = pd.DataFrame(
        {
            "EPS Estimate": [1.20, 1.35, 1.10, 1.05, 0.98, 1.50],
            "Reported EPS": [1.25, 1.30, 1.14, 0.90, np.nan, np.nan],
            "Surprise(%)": [4.1, -3.7, 3.6, -14.3, np.nan, np.nan],
        },
        index=pd.DatetimeIndex(
            ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"]
        ),
    )

    result = _financial_fetch(monkeypatch, _FakeTicker({"trailingPE": 10.0}, frame))

    assert [row["date"] for row in result["earnings_surprise"]["last_4"]] == [
        "2025-12-31",
        "2025-09-30",
        "2025-06-30",
        "2025-03-31",
    ]
    assert result["earnings_surprise"]["last_4"][0] == {
        "date": "2025-12-31",
        "estimate": 1.05,
        "actual": 0.90,
        "surprise_pct": -14.3,
    }
    json.loads(json.dumps(result["earnings_surprise"]))  # JSON boundary holds


def test_empty_info_and_frame_omit_both_keys_without_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rate-limited info (empty dict) and a missing frame degrade to key
    absence — the option/benchmark convention — never to None or a raise."""
    result = _financial_fetch(monkeypatch, _FakeTicker({}, None))

    assert "consensus" not in result
    assert "earnings_surprise" not in result
    assert result["earnings_dates"] == []


# --------------------------------------------------------------------------
# Trend depth: quarterly statements ride the same ticker session
# --------------------------------------------------------------------------


def _quarterly_frames() -> dict[str, pd.DataFrame]:
    """Realistic statement shapes: line-item index, DatetimeIndex columns."""
    return {
        "income": pd.DataFrame(
            {pd.Timestamp("2026-06-30"): [123.0, 45.0], pd.Timestamp("2026-03-31"): [100.0, 40.0]},
            index=["Total Revenue", "Net Income"],
        ),
        "balance": pd.DataFrame(
            {pd.Timestamp("2026-06-30"): [500.0], pd.Timestamp("2026-03-31"): [480.0]},
            index=["Total Assets"],
        ),
        "cash": pd.DataFrame(
            {pd.Timestamp("2026-06-30"): [12.0], pd.Timestamp("2026-03-31"): [10.0]},
            index=["Operating Cash Flow"],
        ),
    }


def test_quarterly_statements_ride_the_financial_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Trend depth on: the three quarterly statements flow through the same
    stmt_converter (visibility stamps included) under statements_quarterly —
    annual frames alone can't show inflection points inside the year."""
    frames = _quarterly_frames()

    def _converter(df: pd.DataFrame) -> dict[str, Any]:
        return {"rows": list(df.index), "cols": [d.strftime("%Y-%m-%d") for d in df.columns]}

    monkeypatch.setattr(
        data_agent_mod.yf, "Ticker", lambda _s: _FakeTicker({"trailingPE": 10.0}, None, frames)
    )
    result = data_agent_mod._sync_fetch_financial_data("AAPL", "AAPL", _converter)

    block = result["statements_quarterly"]
    assert block["income_statement"]["rows"] == ["Total Revenue", "Net Income"]
    assert block["income_statement"]["cols"] == ["2026-06-30", "2026-03-31"]
    assert block["balance_sheet"]["rows"] == ["Total Assets"]
    assert block["cash_flow"]["rows"] == ["Operating Cash Flow"]


def test_trend_depth_off_omits_quarterly_statements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Toggle off = exactly the pre-trend payload: annual statements only."""
    monkeypatch.setattr(get_settings(), "trend_depth_enabled", False)

    result = _financial_fetch(
        monkeypatch, _FakeTicker({"trailingPE": 10.0}, None, _quarterly_frames())
    )

    assert "statements_quarterly" not in result
    assert "income_statement" in result  # annual statements untouched


def test_missing_quarterly_attrs_omit_the_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ticker without the quarterly aliases (older yfinance, stripped fake)
    must degrade to key absence via getattr — never an AttributeError."""
    ticker = _FakeTicker({"trailingPE": 10.0}, None, _quarterly_frames())
    del ticker.quarterly_income_stmt, ticker.quarterly_balance_sheet
    del ticker.quarterly_cashflow
    monkeypatch.setattr(data_agent_mod.yf, "Ticker", lambda _s: ticker)

    result = data_agent_mod._sync_fetch_financial_data("AAPL", "AAPL", lambda _df: {})

    assert "statements_quarterly" not in result


# --------------------------------------------------------------------------
# Wiring: the execute-level tail merge keeps CN precedence intact
# --------------------------------------------------------------------------


def _info_draft() -> dict[str, Any]:
    return {
        "status": "ok",
        "target_price": {
            "count": 25,
            "mean": 250.0,
            "median": 245.0,
            "low": 180.0,
            "high": 300.0,
            "implied_upside": 0.25,
        },
        "ratings": {
            "counts": {"买入": 0, "增持": 0, "中性": 0, "减持": 0, "卖出": 0},
            "dominant": "buy",
            "mean": 2.1,
            "total": 25,
        },
    }


def _finnhub_block() -> dict[str, Any]:
    return {
        "status": "insufficient_data",
        "ratings": {
            "counts": {"买入": 12, "增持": 8, "中性": 3, "减持": 1, "卖出": 0},
            "dominant": "买入",
            "total": 24,
        },
    }


def _cn_block() -> dict[str, Any]:
    return {
        "status": "ok",
        "eps_forecast": {"year1": 2026, "eps_mean": 1.53, "org_count": 15},
        "target_price": {"count": 4, "mean": 9.75, "median": 9.5, "window_days": 180},
        "ratings": {
            "counts": {"买入": 2, "增持": 1, "中性": 1, "减持": 0, "卖出": 0},
            "dominant": "买入",
            "total": 4,
        },
    }


def _patch_run(
    monkeypatch: pytest.MonkeyPatch,
    financials: dict[str, dict[str, Any]],
    *,
    cn_block: dict[str, Any] | None,
    us_block: dict[str, Any] | None,
) -> None:
    """Stub per-symbol collection and both consensus seams so execute()
    exercises only the tail merge (the tail-concurrency test's pattern)."""

    async def _fake_collect(self, symbol: str) -> dict[str, Any]:
        return {
            "market_data": {"symbol": symbol},
            "financial_data": financials.get(symbol, {}),
            "news_data": [],
        }

    async def _fake_cn_consensus(symbol: str, current_price: float | None = None):
        return cn_block

    async def _fake_us_consensus(symbol: str):
        return us_block

    async def _fake_benchmark(ticker: str):
        return {"symbol": ticker, "dates": ["2026-01-02"], "close": [4800.0]}

    async def _no_cn_sector_benchmark(symbol: str):
        return None

    monkeypatch.setattr(data_agent_mod.DataCollectionAgent, "_collect_symbol_data", _fake_collect)
    monkeypatch.setattr(get_settings(), "option_signals_enabled", False)
    monkeypatch.setattr(data_agent_mod, "fetch_benchmark_history", _fake_benchmark)
    monkeypatch.setattr(data_agent_mod, "fetch_cn_sector_benchmark", _no_cn_sector_benchmark)
    monkeypatch.setattr(data_agent_mod, "fetch_cn_consensus", _fake_cn_consensus)
    monkeypatch.setattr(data_agent_mod, "fetch_us_consensus", _fake_us_consensus)


@pytest.mark.asyncio
async def test_cn_block_survives_wholesale_and_us_draft_merges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one-line CN precedence pin: a staged pre-existing CN consensus is
    replaced by the fetched THS/Sina block untouched (never merged with the
    info draft), while AAPL's draft merges under the fetched Finnhub block —
    target_price from info, band counts from Finnhub, status upgraded to ok
    by the hard-number evidence."""
    _patch_run(
        monkeypatch,
        {
            "AAPL": {"metrics": {}, "consensus": _info_draft()},
            # Decoy: proves the fetched CN block replaces whatever preceded
            # it wholesale (the real sync leg stages nothing for CN at all).
            "600000": {"metrics": {}, "consensus": {"status": "insufficient_data"}},
        },
        cn_block=_cn_block(),
        us_block=_finnhub_block(),
    )

    agent = data_agent_mod.DataCollectionAgent(name="data_collection")
    result = await agent.execute({"symbols": ["AAPL", "600000"]})

    assert result["financial_data"]["600000"]["consensus"] == _cn_block()
    assert result["financial_data"]["AAPL"]["consensus"] == {
        "status": "ok",
        "target_price": _info_draft()["target_price"],
        "ratings": _finnhub_block()["ratings"],
    }


@pytest.mark.asyncio
async def test_us_draft_stands_when_finnhub_has_no_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Finnhub answer (None is the absence convention) leaves the staged
    info draft as the consensus record — the zero-network fallback."""
    _patch_run(
        monkeypatch,
        {"AAPL": {"metrics": {}, "consensus": _info_draft()}},
        cn_block=None,
        us_block=None,
    )

    agent = data_agent_mod.DataCollectionAgent(name="data_collection")
    result = await agent.execute({"symbols": ["AAPL"]})

    assert result["financial_data"]["AAPL"]["consensus"] == _info_draft()


@pytest.mark.asyncio
async def test_no_draft_and_no_block_keeps_the_key_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both sources silent (thin coverage everywhere) → the consensus key
    stays absent, exactly as before the info draft existed."""
    _patch_run(monkeypatch, {"AAPL": {"metrics": {}}}, cn_block=None, us_block=None)

    agent = data_agent_mod.DataCollectionAgent(name="data_collection")
    result = await agent.execute({"symbols": ["AAPL"]})

    assert "consensus" not in result["financial_data"]["AAPL"]
