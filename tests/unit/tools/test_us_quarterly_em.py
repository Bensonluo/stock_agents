"""US quarterly income fallback (East Money 单季报) — offline pins.

Production context (verified live 2026-09-25 in the deploy container, see
test_us_sources_fallback): the Tencent Cloud host is rate-limited by Yahoo
on every endpoint, so the yfinance quarterly frames behind
trend_depth_enabled are dark there — quarterly_statement_trends' US leg
never fires in production. akshare's stock_financial_us_report_em
(综合损益表, 单季报) serves PRE-DIFFERENCED discrete quarters over the same
CN network the akshare CN legs already use, so it fills the dark leg.

These tests pin, fully offline: the long→wire converter (pivot, row
candidate mapping, NaN handling, visibility stamps), the fetch function's
degrade-to-None contract via a fake akshare module, and the data-agent
fill-only wiring — yfinance precedence, US-only guard, key-absent degrade.
"""

from __future__ import annotations

import sys
import types
from datetime import date, timedelta
from typing import Any

import pandas as pd
import pytest

import app.agents.data_agent as data_agent_mod
from app.backtest.point_in_time import DEFAULT_REPORTING_LAG_DAYS
from app.tools.data.fetcher_us_quarterly import (
    fetch_us_quarterly_income_em,
    quarterly_income_from_em,
)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _em_frame(rows: list[tuple[str, str, float | None]]) -> pd.DataFrame:
    """Long-format frame mimicking stock_financial_us_report_em output."""
    return pd.DataFrame(
        [
            {"REPORT_DATE": d, "REPORT_TYPE": "单季报", "REPORT": "x", "ITEM_NAME": i, "AMOUNT": a}
            for d, i, a in rows
        ]
    )


# --- converter: pivot, mapping, stamps -------------------------------------


def test_converter_pivots_long_frame_to_wire_shape():
    frame = _em_frame(
        [
            ("2026-06-27 00:00:00", "主营收入", 109.417e9),
            ("2026-03-28 00:00:00", "主营收入", 111.184e9),
            ("2025-12-27 00:00:00", "主营收入", 143.756e9),
            ("2025-09-27 00:00:00", "主营收入", 102.466e9),
            ("2026-06-27 00:00:00", "归属于母公司股东净利润", 29.7e9),
            ("2026-03-28 00:00:00", "归属于母公司股东净利润", 29.5e9),
            ("2025-12-27 00:00:00", "归属于母公司股东净利润", 42.0e9),
            ("2025-09-27 00:00:00", "归属于母公司股东净利润", 27.4e9),
            # unrelated line item — never surfaces in the wire rows
            ("2026-06-27 00:00:00", "研发费用", 8.5e9),
        ]
    )
    result = quarterly_income_from_em(frame)
    assert isinstance(result, dict)
    assert set(result) == {"income_statement"}  # income only — no balance/cash
    income = result["income_statement"]
    # provider frame is newest-first; wire dates come oldest → newest
    assert income["dates"] == ["2025-09-27", "2025-12-27", "2026-03-28", "2026-06-27"]
    assert set(income["data"]) == {"Total Revenue", "Net Income"}
    assert income["data"]["Total Revenue"] == [102.466e9, 143.756e9, 111.184e9, 109.417e9]
    assert income["data"]["Net Income"] == [27.4e9, 42.0e9, 29.5e9, 29.7e9]
    # visibility stamps align index-wise with dates (backtest no-peek)
    stamped = [date.fromisoformat(d) for d in income["visible_from"]]
    assert stamped == [
        date.fromisoformat(d) + timedelta(days=DEFAULT_REPORTING_LAG_DAYS) for d in income["dates"]
    ]


def test_converter_revenue_falls_back_to_second_candidate():
    frame = _em_frame(
        [("2026-06-27 00:00:00", "营业收入", 100.0), ("2026-03-28 00:00:00", "营业收入", 90.0)]
        + [
            ("2026-06-27 00:00:00", "净利润", 10.0),
            ("2026-03-28 00:00:00", "净利润", 9.0),
        ]
    )
    result = quarterly_income_from_em(frame)
    assert result is not None
    assert result["income_statement"]["data"]["Total Revenue"] == [90.0, 100.0]


def test_converter_net_income_prefers_parent_attributed():
    frame = _em_frame(
        [
            ("2026-06-27 00:00:00", "归属于母公司股东净利润", 11.0),
            ("2026-03-28 00:00:00", "归属于母公司股东净利润", 10.0),
            # broader 净利润 also present — must NOT win
            ("2026-06-27 00:00:00", "净利润", 99.0),
            ("2026-03-28 00:00:00", "净利润", 98.0),
        ]
    )
    result = quarterly_income_from_em(frame)
    assert result is not None
    assert result["income_statement"]["data"]["Net Income"] == [10.0, 11.0]


def test_converter_skips_candidate_with_too_few_points():
    # 主营收入 has only ONE usable point → skipped for the next candidate
    frame = _em_frame(
        [
            ("2026-06-27 00:00:00", "主营收入", 100.0),
            ("2026-06-27 00:00:00", "营业收入", 80.0),
            ("2026-03-28 00:00:00", "营业收入", 70.0),
            ("2026-06-27 00:00:00", "净利润", 10.0),
            ("2026-03-28 00:00:00", "净利润", 9.0),
        ]
    )
    result = quarterly_income_from_em(frame)
    assert result is not None
    assert result["income_statement"]["data"]["Total Revenue"] == [70.0, 80.0]


def test_converter_nan_becomes_none_and_gaps_stay_none():
    frame = _em_frame(
        [
            ("2026-06-27 00:00:00", "主营收入", float("nan")),
            ("2026-03-28 00:00:00", "主营收入", 90.0),
            ("2025-12-27 00:00:00", "主营收入", 80.0),
            # net income covers a quarter revenue doesn't — per-row windows
            ("2026-06-27 00:00:00", "净利润", 10.0),
            ("2026-03-28 00:00:00", "净利润", 9.0),
        ]
    )
    result = quarterly_income_from_em(frame)
    assert result is not None
    assert result["income_statement"]["data"]["Total Revenue"] == [80.0, 90.0, None]


def test_converter_returns_none_when_no_usable_rows():
    assert quarterly_income_from_em(pd.DataFrame()) is None
    assert quarterly_income_from_em(_em_frame([("2026-06-27 00:00:00", "研发费用", 1.0)])) is None
    all_nan = _em_frame(
        [
            ("2026-06-27 00:00:00", "主营收入", float("nan")),
            ("2026-03-28 00:00:00", "主营收入", float("nan")),
        ]
    )
    assert quarterly_income_from_em(all_nan) is None


def test_converter_duplicate_date_keeps_last_amount():
    frame = _em_frame(
        [
            ("2026-06-27 00:00:00", "主营收入", 100.0),
            ("2026-03-28 00:00:00", "主营收入", 90.0),
            ("2026-06-27 00:00:00", "净利润", 10.0),
            ("2026-03-28 00:00:00", "净利润", 9.0),
            # restatement-style duplicate for the newest revenue quarter
            ("2026-06-27 00:00:00", "主营收入", 101.0),
        ]
    )
    result = quarterly_income_from_em(frame)
    assert result is not None
    assert result["income_statement"]["data"]["Total Revenue"] == [90.0, 101.0]


# --- fetch: degrade contract with a fake akshare ---------------------------


def _install_fake_akshare(monkeypatch, df_or_exc: Any) -> None:
    def _call(*_args: Any, **_kwargs: Any) -> Any:
        if isinstance(df_or_exc, BaseException):
            raise df_or_exc
        return df_or_exc

    fake = types.ModuleType("akshare")
    fake.stock_financial_us_report_em = _call
    monkeypatch.setitem(sys.modules, "akshare", fake)


def test_fetch_returns_stamped_block_for_good_frame(monkeypatch):
    frame = _em_frame(
        [
            ("2026-06-27 00:00:00", "主营收入", 100.0),
            ("2026-03-28 00:00:00", "主营收入", 90.0),
            ("2026-06-27 00:00:00", "净利润", 10.0),
            ("2026-03-28 00:00:00", "净利润", 9.0),
        ]
    )
    _install_fake_akshare(monkeypatch, frame)
    result = fetch_us_quarterly_income_em("AAPL")
    assert result is not None
    assert "income_statement" in result
    assert "visible_from" in result["income_statement"]


def test_fetch_degrades_to_none_on_endpoint_error(monkeypatch):
    _install_fake_akshare(monkeypatch, ConnectionError("EM endpoint dark"))
    assert fetch_us_quarterly_income_em("AAPL") is None


def test_fetch_degrades_to_none_on_empty_frame(monkeypatch):
    _install_fake_akshare(monkeypatch, pd.DataFrame())
    assert fetch_us_quarterly_income_em("AAPL") is None


def test_fetch_degrades_to_none_without_akshare(monkeypatch):
    monkeypatch.setitem(sys.modules, "akshare", None)
    assert fetch_us_quarterly_income_em("AAPL") is None


# --- data-agent wiring: fill-only, yfinance precedence, US-only -------------


_QUARTERLY: dict[str, Any] = {
    "income_statement": {
        "dates": ["2026-03-28", "2026-06-27"],
        "data": {"Total Revenue": [90.0, 100.0], "Net Income": [9.0, 10.0]},
        "visible_from": ["2026-05-27", "2026-08-26"],
    }
}


async def _run_financial(monkeypatch, symbol: str, sync_result: dict, spy: Any = None) -> dict:
    monkeypatch.setattr(data_agent_mod, "_sync_fetch_financial_data", lambda *a, **k: sync_result)
    target = spy if spy is not None else (lambda _symbol: _QUARTERLY)
    monkeypatch.setattr(data_agent_mod, "fetch_us_quarterly_income_em", target)
    agent = data_agent_mod.DataCollectionAgent(name="data_collection")
    return await agent._fetch_financial_data(symbol)


@pytest.mark.asyncio
async def test_wiring_fills_missing_statements_quarterly(monkeypatch):
    result = await _run_financial(
        monkeypatch, "AAPL", {"metrics": {"pe_ratio": 30.0}, "symbol": "AAPL"}
    )
    assert result["statements_quarterly"] == _QUARTERLY


@pytest.mark.asyncio
async def test_wiring_yfinance_result_keeps_precedence(monkeypatch):
    calls: list[str] = []

    def _spy(_symbol: str) -> None:
        calls.append(_symbol)
        return None

    live = {
        "metrics": {"pe_ratio": 30.0},
        "symbol": "AAPL",
        "statements_quarterly": {"income_statement": {"dates": ["2026-06-27"], "data": {}}},
    }
    result = await _run_financial(monkeypatch, "AAPL", live, spy=_spy)
    assert calls == []  # never consulted when yfinance already supplied it
    assert result["statements_quarterly"] is live["statements_quarterly"]


@pytest.mark.asyncio
async def test_wiring_degrades_to_key_absent(monkeypatch):
    result = await _run_financial(
        monkeypatch, "AAPL", {"metrics": {"pe_ratio": 30.0}}, spy=lambda _s: None
    )
    assert "statements_quarterly" not in result


@pytest.mark.asyncio
async def test_wiring_us_only_cn_and_hk_skip_the_fallback(monkeypatch):
    calls: list[str] = []

    def _spy(_symbol: str) -> None:
        calls.append(_symbol)
        return None

    for symbol in ("600519", "3690.HK"):
        result = await _run_financial(
            monkeypatch, symbol, {"metrics": {"pe_ratio": 30.0}}, spy=_spy
        )
        assert "statements_quarterly" not in result
    assert calls == []
