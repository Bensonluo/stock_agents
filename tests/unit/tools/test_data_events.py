"""Upcoming catalyst/event calendar (data layer).

Contract (report layer): financial_data[symbol]["event_calendar"] =
{"upcoming": [{date, type, title, detail?}, ...], "as_of": ...} — upcoming
only (date >= today), ascending, max 8, undated rows dropped, provider
failures contribute nothing, nothing at all → key absent.

Providers are dependency-injected (fake akshare module / fake yfinance
ticker) so every test here is hermetic; the single live smoke test is
marked network.
"""

from __future__ import annotations

import json
import types
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import pytest

import app.agents.data_agent as data_agent_mod
from app.config import get_settings
from app.tools.data import fetcher as fetcher_module
from app.tools.data.fetcher_events import (
    MAX_UPCOMING_EVENTS,
    SPLIT_LOOKBACK_DAYS,
    _report_periods,
    build_event_calendar,
)


def _today() -> date:
    return date.today()


def _iso(days_from_today: int) -> str:
    return (_today() + timedelta(days=days_from_today)).isoformat()


def _dt(days_from_today: int) -> datetime:
    return datetime(_today().year, _today().month, _today().day) + timedelta(days=days_from_today)


# ── Fakes ───────────────────────────────────────────────────────────


class _FakeTicker:
    """yfinance ticker stand-in: calendar/dividends/splits configurable
    (properties so failure paths can raise exactly like a rate-limited
    attribute access), plus the financial-leg attributes the sync fetch
    reads before the calendar wiring runs."""

    def __init__(
        self,
        *,
        calendar: Any = None,
        dividends: Any = None,
        splits: Any = None,
        fail_calendar: bool = False,
    ):
        self.info: dict = {}
        self.income_stmt = pd.DataFrame()
        self.balance_sheet = pd.DataFrame()
        self.cashflow = pd.DataFrame()
        self.earnings_dates = None
        self._calendar = calendar
        self._dividends = dividends
        self._splits = splits
        self._fail_calendar = fail_calendar

    @property
    def calendar(self):
        if self._fail_calendar:
            raise RuntimeError("rate limited")
        return self._calendar

    @property
    def dividends(self):
        return self._dividends

    @property
    def splits(self):
        return self._splits


def _install_fake_akshare(
    *,
    yjyg: pd.DataFrame | None = None,
    yjyg_error: Exception | None = None,
    queue: pd.DataFrame | None = None,
    queue_error: Exception | None = None,
    fhps: pd.DataFrame | None = None,
    fhps_error: Exception | None = None,
    calls: list | None = None,
) -> types.ModuleType:
    """Fake akshare module with the three CN event endpoints."""

    def _yjyg(date: str = "20260630"):
        if calls is not None:
            calls.append(("stock_yjyg_em", date))
        if yjyg_error is not None:
            raise yjyg_error
        return yjyg

    def _queue(symbol: str = "600000"):
        if calls is not None:
            calls.append(("stock_restricted_release_queue_em", symbol))
        if queue_error is not None:
            raise queue_error
        return queue

    def _fhps(symbol: str = "600000"):
        if calls is not None:
            calls.append(("stock_fhps_detail_em", symbol))
        if fhps_error is not None:
            raise fhps_error
        return fhps

    mod = types.ModuleType("akshare")
    mod.stock_yjyg_em = _yjyg
    mod.stock_restricted_release_queue_em = _queue
    mod.stock_fhps_detail_em = _fhps
    return mod


_YJYG_COLS = [
    "序号",
    "股票代码",
    "股票简称",
    "预测指标",
    "业绩变动",
    "预测数值",
    "业绩变动幅度",
    "业绩变动原因",
    "预告类型",
    "上年同期值",
    "公告日期",
]
_QUEUE_COLS = [
    "序号",
    "解禁时间",
    "解禁股东数",
    "解禁数量",
    "实际解禁数量",
    "未解禁数量",
    "实际解禁数量市值",
    "占总市值比例",
    "占流通市值比例",
    "解禁前一交易日收盘价",
    "限售股类型",
    "解禁前20日涨跌幅",
    "解禁后20日涨跌幅",
]
_FHPS_COLS = [
    "报告期",
    "业绩披露日期",
    "送转股份-送转总比例",
    "送转股份-送股比例",
    "送转股份-转股比例",
    "现金分红-现金分红比例",
    "现金分红-现金分红比例描述",
    "现金分红-股息率",
    "每股收益",
    "每股净资产",
    "每股公积金",
    "每股未分配利润",
    "净利润同比增长",
    "总股本",
    "预案公告日",
    "股权登记日",
    "除权除息日",
    "方案进度",
    "最新公告日期",
]


def _yjyg_df(*rows) -> pd.DataFrame:
    return pd.DataFrame(list(rows), columns=_YJYG_COLS)


def _queue_df(*rows) -> pd.DataFrame:
    return pd.DataFrame(list(rows), columns=_QUEUE_COLS)


def _fhps_frame(**overrides) -> pd.DataFrame:
    """分红送配 frame with one row; column names (hyphens stripped) double
    as keyword arguments, unlisted columns stay None."""
    row = dict.fromkeys(_FHPS_COLS)
    for key, value in overrides.items():
        row[[c for c in _FHPS_COLS if c.replace("-", "") == key][0]] = value
    return pd.DataFrame([tuple(row[c] for c in _FHPS_COLS)], columns=_FHPS_COLS)


# ── US/HK: earnings, ex-dividend, splits ────────────────────────────


def test_us_earnings_list_takes_earliest_upcoming() -> None:
    """Earnings Date as a list (Yahoo's estimate range): past entries are
    ignored and the earliest upcoming date becomes the single event."""
    cal = {"Earnings Date": [_dt(-3), _dt(10), _dt(24)]}
    block = build_event_calendar("AAPL", ticker=_FakeTicker(calendar=cal))
    assert block is not None
    earnings = [e for e in block["upcoming"] if e["type"] == "earnings"]
    assert earnings == [{"date": _iso(10), "type": "earnings", "title": "财报发布"}]


def test_us_earnings_single_datetime_and_past_only_window() -> None:
    cal = {"Earnings Date": _dt(7)}  # scalar shape, not a list
    block = build_event_calendar("AAPL", ticker=_FakeTicker(calendar=cal))
    assert block is not None
    assert any(e["type"] == "earnings" and e["date"] == _iso(7) for e in block["upcoming"])

    past_only = {"Earnings Date": [_dt(-30), _dt(-2)]}
    assert build_event_calendar("AAPL", ticker=_FakeTicker(calendar=past_only)) is None


def test_us_earnings_string_date_parses() -> None:
    cal = {"Earnings Date": _iso(14)}
    block = build_event_calendar("AAPL", ticker=_FakeTicker(calendar=cal))
    assert block is not None
    assert block["upcoming"][0]["date"] == _iso(14)


def test_us_ex_dividend_carries_most_recent_amount() -> None:
    cal = {"Ex-Dividend Date": _dt(9)}
    dividends = pd.Series(
        [0.22, 0.24, 0.25],
        index=pd.DatetimeIndex([_iso(-90), _iso(-60), _iso(-30)]),
    )
    block = build_event_calendar("AAPL", ticker=_FakeTicker(calendar=cal, dividends=dividends))
    divs = [e for e in block["upcoming"] if e["type"] == "dividend"]
    assert divs == [
        {"date": _iso(9), "type": "dividend", "title": "除息日", "detail": {"amount": 0.25}}
    ]


def test_us_ex_dividend_without_dividends_omits_detail() -> None:
    """No dividend history → the event still renders, without a detail dict."""
    cal = {"Ex-Dividend Date": _dt(9)}
    block = build_event_calendar("AAPL", ticker=_FakeTicker(calendar=cal, dividends=None))
    assert block is not None
    divs = [e for e in block["upcoming"] if e["type"] == "dividend"]
    assert divs == [{"date": _iso(9), "type": "dividend", "title": "除息日"}]

    empty = build_event_calendar(
        "AAPL",
        ticker=_FakeTicker(calendar=cal, dividends=pd.Series([], dtype=float)),
    )
    assert empty is not None
    assert all("detail" not in e for e in empty["upcoming"])


def test_us_past_ex_dividend_dropped() -> None:
    cal = {"Ex-Dividend Date": _dt(-5)}
    dividends = pd.Series([0.25], index=pd.DatetimeIndex([_iso(-30)]))
    assert (
        build_event_calendar("AAPL", ticker=_FakeTicker(calendar=cal, dividends=dividends)) is None
    )


def test_us_recent_split_included_with_its_past_date() -> None:
    """The one carve-out from upcoming-only: splits are historical, and a
    split executed within the lookback window is still a live catalyst —
    it rides its actual (past) date."""
    splits = pd.Series(
        [4.0, 2.0],
        index=pd.DatetimeIndex([_iso(-365), _iso(-SPLIT_LOOKBACK_DAYS + 10)]),
    )
    block = build_event_calendar("AAPL", ticker=_FakeTicker(splits=splits))
    assert block is not None
    assert block["upcoming"] == [
        {"date": _iso(-SPLIT_LOOKBACK_DAYS + 10), "type": "split", "title": "拆股"}
    ]


def test_us_split_lookback_boundary_is_inclusive() -> None:
    edge = pd.Series([2.0], index=pd.DatetimeIndex([_iso(-SPLIT_LOOKBACK_DAYS)]))
    block = build_event_calendar("AAPL", ticker=_FakeTicker(splits=edge))
    assert block is not None and block["upcoming"][0]["type"] == "split"

    stale = pd.Series([2.0], index=pd.DatetimeIndex([_iso(-SPLIT_LOOKBACK_DAYS - 1)]))
    assert build_event_calendar("AAPL", ticker=_FakeTicker(splits=stale)) is None


def test_us_calendar_dataframe_shape() -> None:
    """Older yfinance hands back a DataFrame with labels on the index."""
    cal = pd.DataFrame({"0": [_dt(12), _dt(5)]}, index=["Earnings Date", "Ex-Dividend Date"])
    block = build_event_calendar("AAPL", ticker=_FakeTicker(calendar=cal))
    assert block is not None
    assert {e["type"] for e in block["upcoming"]} == {"earnings", "dividend"}


def test_us_calendar_failure_keeps_splits() -> None:
    """A rate-limited calendar degrades alone — the splits history still
    contributes its recent split."""
    splits = pd.Series([3.0], index=pd.DatetimeIndex([_iso(-4)]))
    block = build_event_calendar("AAPL", ticker=_FakeTicker(fail_calendar=True, splits=splits))
    assert block is not None
    assert block["upcoming"] == [{"date": _iso(-4), "type": "split", "title": "拆股"}]


def test_us_bare_ticker_yields_none() -> None:
    """A ticker with none of the three attributes (mock surfaces, exotic
    providers) contributes nothing and never raises."""
    assert build_event_calendar("AAPL", ticker=object()) is None
    assert build_event_calendar("AAPL", ticker=None) is None


# ── CN: 业绩预告 / 解禁 / 分红送配 ─────────────────────────────────────


def test_cn_preannouncement_future_kept_past_dropped() -> None:
    """Future 公告日期 rows survive; past, foreign-symbol and undated rows
    are dropped."""
    df = _yjyg_df(
        (
            1,
            "600000",
            "浦发银行",
            "每股收益",
            "预增",
            1.53,
            20.0,
            "主业增长",
            "预增",
            1.27,
            _iso(5),
        ),
        (
            2,
            "600000",
            "浦发银行",
            "每股收益",
            "预增",
            1.40,
            10.0,
            "主业增长",
            "预增",
            1.27,
            _iso(-2),
        ),
        (3, "600036", "招商银行", "每股收益", "预增", 5.0, 15.0, "主业增长", "预增", 4.3, _iso(6)),
        (
            4,
            "600000",
            "浦发银行",
            "净利润",
            "预增",
            300.0,
            10.0,
            "主业增长",
            "预增",
            270.0,
            "unknown",
        ),
    )
    ak = _install_fake_akshare(yjyg=df)
    block = build_event_calendar("600000", akshare_module=ak)
    assert block is not None
    assert block["upcoming"] == [
        {
            "date": _iso(5),
            "type": "preannouncement",
            "title": "业绩预告",
            "detail": {"eps_hint": 1.53},
        }
    ]


def test_cn_preannouncement_eps_hint_rules() -> None:
    """Only a numeric 预测数值 on a per-share indicator becomes eps_hint —
    net-profit forecasts and range strings are not EPS."""
    df = _yjyg_df(
        (1, "600000", "浦发银行", "净利润", "预增", 300.0, 10.0, "x", "预增", 270.0, _iso(5)),
        (2, "600000", "浦发银行", "每股收益", "预增", "0.53~0.58", 10.0, "x", "预增", 0.5, _iso(6)),
    )
    ak = _install_fake_akshare(yjyg=df)
    block = build_event_calendar("600000", akshare_module=ak)
    assert block is not None
    assert len(block["upcoming"]) == 2
    assert all("detail" not in e for e in block["upcoming"])


def test_cn_unlock_detail_and_past_filter() -> None:
    """Live-shape primary case: the provider's 占总市值比例 is a decimal
    fraction (0.0211 = 2.11%) and passes through unscaled; a literal '%'
    suffix is stripped defensively (row 2 is past-dated and dropped)."""
    df = _queue_df(
        (
            1,
            _iso(21),
            3,
            457_665_903,
            457_665_903,
            0,
            1.2e9,
            0.021100868588,
            5.0,
            10.0,
            "定增",
            1.0,
            2.0,
        ),
        (2, _iso(-4), 1, 50_000, 50_000, 0, 5e8, "1.00%", 2.0, 9.0, "定增", 0.5, 1.0),
    )
    ak = _install_fake_akshare(queue=df)
    block = build_event_calendar("600000", akshare_module=ak)
    assert block is not None
    assert block["upcoming"] == [
        {
            "date": _iso(21),
            "type": "unlock",
            "title": "限售解禁",
            "detail": {"shares": 457_665_903, "pct_of_float": 0.021100868588},
        }
    ]


def test_cn_unlock_without_detail_columns_still_fires() -> None:
    """A frame missing every detail column degrades to a bare unlock event."""
    df = pd.DataFrame({"股票代码": ["600000"], "解禁时间": [_iso(11)]})
    ak = _install_fake_akshare(queue=df)
    block = build_event_calendar("600000", akshare_module=ak)
    assert block is not None
    assert block["upcoming"] == [{"date": _iso(11), "type": "unlock", "title": "限售解禁"}]


def test_cn_dividend_ex_and_record_dates() -> None:
    """Both upcoming dates on one row fire; the record date sorts before the
    ex-dividend date; the amount rides the CN 10派N numeric ratio."""
    df = _fhps_frame(
        现金分红现金分红比例=3.5,
        现金分红现金分红比例描述="10派3.5元(含税)",
        现金分红股息率=4.2,
        股权登记日=_iso(8),
        除权除息日=_iso(10),
        方案进度="实施",
    )
    ak = _install_fake_akshare(fhps=df)
    block = build_event_calendar("600000", akshare_module=ak)
    assert block is not None
    assert block["upcoming"] == [
        {
            "date": _iso(8),
            "type": "dividend",
            "title": "股权登记日",
            "detail": {"amount": 3.5, "yield_pct": 4.2},
        },
        {
            "date": _iso(10),
            "type": "dividend",
            "title": "除息日",
            "detail": {"amount": 3.5, "yield_pct": 4.2},
        },
    ]


def test_cn_dividend_amount_from_description_fallback() -> None:
    """预案 rows often carry the 10派N description only — the amount parses
    out of it; a row without any upcoming date contributes nothing."""
    ak = _install_fake_akshare(
        fhps=_fhps_frame(现金分红现金分红比例描述="10派2.7元(含税)", 除权除息日=_iso(9))
    )
    block = build_event_calendar("600000", akshare_module=ak)
    assert block is not None
    assert block["upcoming"] == [
        {"date": _iso(9), "type": "dividend", "title": "除息日", "detail": {"amount": 2.7}}
    ]

    ak = _install_fake_akshare(fhps=_fhps_frame(现金分红现金分红比例描述="10派2.7元(含税)"))
    assert build_event_calendar("600000", akshare_module=ak) is None


def test_cn_provider_failure_isolates_legs() -> None:
    """业绩预告 down → the 解禁 leg still contributes (and vice versa)."""
    queue = _queue_df((1, _iso(15), 2, 900_000, 900_000, 0, 9e8, 1.5, 3.0, 10.0, "定增", 0.0, 0.0))
    ak = _install_fake_akshare(yjyg_error=RuntimeError("em down"), queue=queue)
    block = build_event_calendar("600000", akshare_module=ak)
    assert block is not None
    assert [e["type"] for e in block["upcoming"]] == ["unlock"]

    reverse = _install_fake_akshare(
        yjyg=_yjyg_df(
            (1, "600000", "浦发银行", "每股收益", "预增", 1.5, 5.0, "x", "预增", 1.4, _iso(3))
        ),
        queue_error=RuntimeError("em down"),
        fhps_error=RuntimeError("em down"),
    )
    block = build_event_calendar("600000", akshare_module=reverse)
    assert block is not None
    assert [e["type"] for e in block["upcoming"]] == ["preannouncement"]


def test_cn_all_providers_dark_returns_none() -> None:
    ak = _install_fake_akshare(
        yjyg_error=RuntimeError("down"),
        queue_error=RuntimeError("down"),
        fhps_error=RuntimeError("down"),
    )
    assert build_event_calendar("600000", akshare_module=ak) is None


def test_cn_report_period_calls_cover_floor_and_ceil() -> None:
    """The whole-market 业绩预告 endpoint is queried once per in-window
    report period (floor + ceil quarter-ends, deduped on quarter-end days)."""
    assert _report_periods(date(2026, 9, 30)) == ["20260930"]
    assert _report_periods(date(2026, 9, 25)) == ["20260630", "20260930"]
    assert _report_periods(date(2027, 1, 5)) == ["20261231", "20270331"]
    assert _report_periods(date(2026, 12, 31)) == ["20261231"]

    calls: list = []
    ak = _install_fake_akshare(yjyg=_yjyg_df(), calls=calls)
    build_event_calendar("600000", akshare_module=ak)
    yjyg_periods = [period for name, period in calls if name == "stock_yjyg_em"]
    assert yjyg_periods == _report_periods(_today())


def test_cn_int_and_float_codes_matched() -> None:
    """East Money codes may arrive as ints or float artifacts — normalization
    must match them against the 6-digit query."""
    df = _queue_df(
        (1, _iso(30), 1, 100, 100, 0, 1e7, 0.1, 0.2, 10.0, "x", 0.0, 0.0),
        (2, _iso(31), 1, 100, 100, 0, 1e7, 0.1, 0.2, 10.0, "x", 0.0, 0.0),
    )
    df["股票代码"] = [600000, 600036.0]
    ak = _install_fake_akshare(queue=df)
    block = build_event_calendar("600000", akshare_module=ak)
    assert block is not None
    assert [e["date"] for e in block["upcoming"]] == [_iso(30)]


# ── Dispatch and block shape ────────────────────────────────────────


def test_non_cn_symbol_never_touches_akshare() -> None:
    """Market dispatch is structural: a US symbol consults only the ticker,
    a CN symbol only the akshare module."""

    def _explode(*_args, **_kwargs):
        raise AssertionError("akshare must not be called for a US symbol")

    ak = types.ModuleType("akshare")
    ak.stock_yjyg_em = _explode
    ak.stock_restricted_release_queue_em = _explode
    ak.stock_fhps_detail_em = _explode

    cal = {"Earnings Date": _dt(3)}
    block = build_event_calendar("AAPL", ticker=_FakeTicker(calendar=cal), akshare_module=ak)
    assert block is not None
    assert block["upcoming"][0]["type"] == "earnings"


def test_cn_symbol_ignores_the_ticker() -> None:
    """CN precedence: a rich Yahoo calendar cannot leak into a 6-digit block
    (Yahoo's CN calendars are junk; akshare is the only CN source)."""
    cal = {"Earnings Date": _dt(3), "Ex-Dividend Date": _dt(4)}
    ak = _install_fake_akshare()  # all frames None → nothing contributes
    assert (
        build_event_calendar("600000", ticker=_FakeTicker(calendar=cal), akshare_module=ak) is None
    )


def test_cap_at_8_and_ascending() -> None:
    rows = tuple(
        (i, _iso(i + 1), 1, 100, 100, 0, 1e7, 0.1, 0.2, 10.0, "x", 0.0, 0.0) for i in range(1, 11)
    )
    ak = _install_fake_akshare(queue=_queue_df(*rows))
    block = build_event_calendar("600000", akshare_module=ak)
    assert block is not None
    assert len(block["upcoming"]) == MAX_UPCOMING_EVENTS == 8
    dates = [e["date"] for e in block["upcoming"]]
    assert dates == sorted(dates)
    assert dates[0] == _iso(2)


def test_sorted_ascending_across_providers() -> None:
    df_pre = _yjyg_df(
        (1, "600000", "浦发银行", "每股收益", "预增", 1.5, 5.0, "x", "预增", 1.4, _iso(12))
    )
    df_queue = _queue_df((1, _iso(4), 1, 100, 100, 0, 1e7, 0.1, 0.2, 10.0, "x", 0.0, 0.0))
    df_fhps = _fhps_frame(
        现金分红现金分红比例=2.0,
        现金分红现金分红比例描述="10派2元",
        现金分红股息率=3.0,
        股权登记日=_iso(16),
        除权除息日=_iso(18),
        方案进度="实施",
    )
    ak = _install_fake_akshare(yjyg=df_pre, queue=df_queue, fhps=df_fhps)
    block = build_event_calendar("600000", akshare_module=ak)
    assert block is not None
    assert [(e["date"], e["type"]) for e in block["upcoming"]] == [
        (_iso(4), "unlock"),
        (_iso(12), "preannouncement"),
        (_iso(16), "dividend"),
        (_iso(18), "dividend"),
    ]


def test_as_of_stamp_and_json_round_trip() -> None:
    """The block is pure native JSON: round-trips bit-for-bit, as_of is the
    build date, and share counts survive as ints."""
    df_queue = _queue_df((1, _iso(4), 1, 100.0, 100.0, 0, 1e7, "0.1%", 0.2, 10.0, "x", 0.0, 0.0))
    ak = _install_fake_akshare(queue=df_queue, fhps=_fhps_frame(除权除息日=_iso(6)))
    block = build_event_calendar("600000", akshare_module=ak)
    assert block is not None
    assert block["as_of"] == _today().isoformat()
    assert json.loads(json.dumps(block)) == block
    unlock = next(e for e in block["upcoming"] if e["type"] == "unlock")
    assert isinstance(unlock["detail"]["shares"], int)


def test_fetcher_reexport_parity() -> None:
    """fetcher.py re-exports the dispatch helper — the agent's single import
    point keeps working for the ReAct tools too."""
    assert fetcher_module.build_event_calendar is build_event_calendar


# ── data_agent wiring ───────────────────────────────────────────────

_RICH_CAL = {"Earnings Date": _dt(9), "Ex-Dividend Date": _dt(20)}
_EVENT_BLOCK = {
    "upcoming": [{"date": _iso(9), "type": "earnings", "title": "财报发布"}],
    "as_of": _today().isoformat(),
}


def test_us_wire_attaches_and_toggle_turns_it_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """The US/HK leg builds the calendar off the ticker it already
    constructed, gated on events_enabled."""
    ticker = _FakeTicker(calendar=_RICH_CAL)
    monkeypatch.setattr(data_agent_mod.yf, "Ticker", lambda _symbol: ticker)

    result = data_agent_mod._sync_fetch_financial_data("AAPL", "AAPL", lambda _df: {})
    assert result["event_calendar"]["upcoming"][0]["type"] == "earnings"

    monkeypatch.setattr(get_settings(), "events_enabled", False)
    result = data_agent_mod._sync_fetch_financial_data("AAPL", "AAPL", lambda _df: {})
    assert "event_calendar" not in result


def test_cn_sync_leg_stays_akshare_free(monkeypatch: pytest.MonkeyPatch) -> None:
    """The yfinance financial leg must not stage a CN event calendar (CN
    events ride the async akshare seam) — even when the Yahoo info is rich."""
    ticker = _FakeTicker(calendar=_RICH_CAL)
    monkeypatch.setattr(data_agent_mod.yf, "Ticker", lambda _symbol: ticker)

    result = data_agent_mod._sync_fetch_financial_data("600000", "600000", lambda _df: {})
    assert "event_calendar" not in result
    assert "consensus" not in result  # the pre-existing CN structural split


@pytest.mark.asyncio
async def test_cn_wire_attaches_via_async_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    """CN events land under financial_data[symbol]["event_calendar"] through
    the akshare seam — attached even when the yfinance leg came back thin."""
    seen: list[str] = []

    async def _fake_seam(self, symbol: str):
        seen.append(symbol)
        return _EVENT_BLOCK

    monkeypatch.setattr(
        data_agent_mod,
        "_sync_fetch_financial_data",
        lambda *args, **kwargs: {"metrics": {"pe_ratio": 5.0}},
    )
    monkeypatch.setattr(data_agent_mod.DataCollectionAgent, "_fetch_cn_event_calendar", _fake_seam)

    agent = data_agent_mod.DataCollectionAgent(name="data_collection")
    result = await agent._fetch_financial_data("600000")
    assert seen == ["600000"]
    assert result["event_calendar"] == _EVENT_BLOCK


@pytest.mark.asyncio
async def test_cn_wire_toggle_off_skips_the_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def _spy_seam(self, symbol: str):
        calls.append(symbol)
        return _EVENT_BLOCK

    monkeypatch.setattr(
        data_agent_mod,
        "_sync_fetch_financial_data",
        lambda *args, **kwargs: {"metrics": {"pe_ratio": 5.0}},
    )
    monkeypatch.setattr(data_agent_mod.DataCollectionAgent, "_fetch_cn_event_calendar", _spy_seam)
    monkeypatch.setattr(get_settings(), "events_enabled", False)

    agent = data_agent_mod.DataCollectionAgent(name="data_collection")
    result = await agent._fetch_financial_data("600000")
    assert calls == []
    assert "event_calendar" not in result


@pytest.mark.asyncio
async def test_cn_events_survive_provider_chain_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """A provider-chain fallback block (no events of its own) must not drop
    the calendar — the seam attaches after the fallback resolution."""

    async def _fake_seam(self, symbol: str):
        return _EVENT_BLOCK

    async def _fake_fallback(symbol: str):
        return {"financial_data": {"metrics": {"pe_ratio": 6.0}, "symbol": symbol}}

    monkeypatch.setattr(data_agent_mod, "_sync_fetch_financial_data", lambda *args, **kwargs: {})
    monkeypatch.setattr(data_agent_mod, "fetch_stock_data", _fake_fallback)
    monkeypatch.setattr(data_agent_mod.DataCollectionAgent, "_fetch_cn_event_calendar", _fake_seam)

    agent = data_agent_mod.DataCollectionAgent(name="data_collection")
    result = await agent._fetch_financial_data("600000")
    assert result["metrics"] == {"pe_ratio": 6.0}
    assert result["event_calendar"] == _EVENT_BLOCK


# ── Live smoke (deselected by default: addopts -m 'not network') ────


@pytest.mark.network
def test_live_smoke_providers_do_not_crash() -> None:
    """Live akshare + yfinance round-trip: only asserts the never-raise
    contract (dict or None), never specific data."""
    import akshare as ak
    import yfinance as yf

    cn = build_event_calendar("600519", akshare_module=ak)
    assert cn is None or isinstance(cn, dict)
    us = build_event_calendar("AAPL", ticker=yf.Ticker("AAPL"))
    assert us is None or isinstance(us, dict)
