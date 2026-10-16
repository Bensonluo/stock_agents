"""Per-stock upcoming catalyst/event calendar (data layer).

The report layer reads ``financial_data[symbol]["event_calendar"]``:

    {"upcoming": [
        {"date": "YYYY-MM-DD",   # event date (公告日 for preannouncement/unlock)
         "type": "earnings" | "dividend" | "split" | "preannouncement" | "unlock" | "other",
         "title": "<short zh label>",
         "detail": {...}},       # OPTIONAL compact dict, only when meaningful
        ...],
     "as_of": "YYYY-MM-DD"}

Rules: upcoming only (event date >= today); ascending by date; capped at
MAX_UPCOMING_EVENTS; undated rows dropped; every provider failure
(exception / empty frame / missing column) makes that provider contribute
nothing and never raises; nothing at all → the caller omits the key.

US/HK — the yfinance Ticker the financial leg already constructed:
    calendar   dict {"Earnings Date": dt | list[dt], "Ex-Dividend Date": dt,
                     ...} (older yfinance may hand back a DataFrame — both
                     shapes read defensively). Earliest upcoming earnings
                     date wins; a past-only window contributes nothing.
    dividends  Series date -> per-share amount; the most recent value
               annotates the next ex-dividend event ({amount}). No upcoming
               ex-div in the calendar → dividends are skipped entirely.
    splits     Series date -> ratio, strictly historical: the last executed
               split is included only when dated within SPLIT_LOOKBACK_DAYS
               (the single carve-out from the upcoming-only filter — a very
               recent split is still a live catalyst, a stale one is noise).

CN (6-digit) — akshare East Money endpoints (1.18.96, column contracts
read from the installed source):
    stock_yjyg_em(date=report_period)  whole-market 业绩预告 for ONE report
        period [序号, 股票代码, 股票简称, 预测指标, 业绩变动, 预测数值, 业绩变动
        幅度, 业绩变动原因, 预告类型, 上年同期值, 公告日期] — fetched for the
        floor and ceil quarter-ends (the announcement windows that can hold
        future-dated rows) and filtered by 股票代码. A numeric 预测数值 on a
        每股收益 indicator becomes detail {eps_hint}; range strings don't
        parse and are omitted.
    stock_restricted_release_queue_em(symbol) 解禁批次 [.., 解禁时间, 解禁数量,
        实际解禁数量, .., 占总市值比例, 占流通市值比例, ..] → unlock with
        detail {shares, pct_of_float?} — shares is 股; pct_of_float is the
        provider's DECIMAL FRACTION as delivered (live 2026-09-30: 601088
        yields 0.0211 for a 2.11% unlock), never rescaled here.
    stock_fhps_detail_em(symbol) 分红送配详情 [报告期, .., 现金分红-现金分红
        比例, .., 现金分红-股息率, .., 预案公告日, 股权登记日, 除权除息日, 方案
        进度, ..] — upcoming 除权除息日 (除息日) and 股权登记日 (股权登记日)
        each yield a dividend event with detail {amount, yield_pct?};
        amount is the CN 10派N convention (per 10 shares), yield_pct the
        provider's decimal fraction (0.042 = 4.2%).

Dependency-injected on purpose: build_event_calendar takes the yfinance
ticker / akshare module so tests are hermetic; the agent passes the real
ones. Pure annotation — nothing in the scoring, risk or decision paths
may read it (the consensus/option_signals convention).
"""

from __future__ import annotations

import math
import re
from datetime import date, timedelta
from typing import Any

import pandas as pd

from app.utils.logging import get_logger

logger = get_logger(__name__)

# Hard cap on "upcoming" entries — the report layer renders a compact
# timeline, not a filing archive.
MAX_UPCOMING_EVENTS = 8

# Splits are historical only; the last executed split is still a live
# catalyst within this window, stale ones are noise.
SPLIT_LOOKBACK_DAYS = 90

# 年报/季报 quarter-ends — the REPORT_DATE values stock_yjyg_em accepts
# (从 20081231 开始). Floor + ceil around today cover both the period whose
# 预告 window just opened and the one currently announcing.
_QUARTER_ENDS = ("0331", "0630", "0930", "1231")

# Rows whose code matches the queried symbol. Codes may arrive zero-padded
# strings, ints (float artifacts like 600000.0 included) — all normalized.
_CODE_COL = "股票代码"


def _to_float(value: Any) -> float | None:
    """Finite native float or None — np.float64/nan/inf/garbage all handled.

    The JSON boundary never accepts numpy types, and NaN poisons every
    downstream round(); refuse them at the door.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _to_int(value: Any) -> int | None:
    number = _to_float(value)
    return None if number is None else int(number)


def _parse_date(value: Any) -> date | None:
    """Coerce the providers' date zoo (datetime/Timestamp/str/YYYYMMDD int)
    into a date; anything unparseable is None, never guessed."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        # YYYYMMDD ints are real dates; epoch-style numbers would silently
        # become 1970 timestamps under pd.to_datetime — refuse them.
        text = str(int(value))
        if len(text) != 8:
            return None
        value = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        parsed = pd.to_datetime(value, errors="coerce")
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    return parsed.date()


def _first_date(row: dict[str, Any], columns: tuple[str, ...]) -> date | None:
    """First parseable date among the candidate columns; undated rows are
    dropped by the caller."""
    for col in columns:
        parsed = _parse_date(row.get(col))
        if parsed is not None:
            return parsed
    return None


def _clean_detail(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Detail dict with the unparseable keys pruned; None when nothing
    meaningful survived (the contract's optional-detail rule)."""
    detail = {key: value for key, value in raw.items() if value is not None}
    return detail or None


def _pct_value(value: Any) -> float | None:
    """Percent number as delivered; a literal '%' suffix is stripped first."""
    if isinstance(value, str):
        value = value.strip().rstrip("%")
    return _to_float(value)


# ── US/HK builders (yfinance ticker) ────────────────────────────────


def _calendar_get(cal: Any, key: str) -> Any:
    """Read one key off ticker.calendar — dict today, DataFrame on older
    yfinance (labels on the index, one value cell)."""
    if isinstance(cal, dict):
        return cal.get(key)
    if isinstance(cal, pd.DataFrame) and not cal.empty:
        try:
            if key in cal.index:
                return cal.loc[key].iloc[0]
        except (KeyError, IndexError):
            return None
    return None


def _as_date_list(value: Any) -> list[date]:
    """Earnings Date arrives as a datetime, a list of datetimes, a Series —
    normalize every shape to parsed dates (unparseable entries dropped)."""
    if value is None or isinstance(value, str | bytes):
        items = [] if value is None else [value]
    elif hasattr(value, "__iter__"):
        items = list(value)
    else:
        items = [value]
    dates = []
    for item in items:
        parsed = _parse_date(item)
        if parsed is not None:
            dates.append(parsed)
    return dates


def _last_dividend_amount(dividends: Any) -> float | None:
    """Most recent per-share dividend off the history Series."""
    if dividends is None:
        return None
    try:
        series = dividends.dropna().sort_index()
    except AttributeError:
        return None
    if series.empty:
        return None
    return _to_float(series.iloc[-1])


def _last_split(splits: Any) -> tuple[date, float] | None:
    """Most recent executed split as (date, ratio); None when absent."""
    if splits is None:
        return None
    try:
        series = splits.dropna().sort_index()
    except AttributeError:
        return None
    if series.empty:
        return None
    when = _parse_date(series.index[-1])
    ratio = _to_float(series.iloc[-1])
    if when is None or ratio is None:
        return None
    return when, ratio


def _us_events(ticker: Any, symbol: str, today: date) -> list[dict[str, Any]]:
    """Upcoming events off the already-constructed yfinance ticker. Each
    attribute access degrades alone — a rate-limited calendar must not take
    the splits history down with it. ``symbol`` is unused (uniform builder
    signature with the CN legs)."""
    if ticker is None:
        return []

    events: list[dict[str, Any]] = []
    try:
        cal = ticker.calendar
    except Exception as e:
        logger.warning(f"[events] ticker.calendar failed: {e}")
        cal = None

    earnings = sorted(d for d in _as_date_list(_calendar_get(cal, "Earnings Date")) if d >= today)
    if earnings:
        events.append({"date": earnings[0].isoformat(), "type": "earnings", "title": "财报发布"})

    try:
        ex_div = _parse_date(_calendar_get(cal, "Ex-Dividend Date"))
    except Exception as e:  # pragma: no cover — _parse_date is already total
        logger.warning(f"[events] ex-dividend read failed: {e}")
        ex_div = None
    if ex_div is not None and ex_div >= today:
        event: dict[str, Any] = {
            "date": ex_div.isoformat(),
            "type": "dividend",
            "title": "除息日",
        }
        try:
            amount = _last_dividend_amount(ticker.dividends)
        except Exception as e:
            logger.warning(f"[events] ticker.dividends failed: {e}")
            amount = None
        detail = _clean_detail({"amount": amount})
        if detail is not None:
            event["detail"] = detail
        events.append(event)

    try:
        last = _last_split(ticker.splits)
    except Exception as e:
        logger.warning(f"[events] ticker.splits failed: {e}")
        last = None
    if last is not None and last[0] >= today - timedelta(days=SPLIT_LOOKBACK_DAYS):
        events.append({"date": last[0].isoformat(), "type": "split", "title": "拆股"})

    return events


# ── CN builders (akshare frames) ────────────────────────────────────


def _symbol_rows(df: pd.DataFrame | None, symbol: str) -> list[dict[str, Any]]:
    """Rows relevant to one symbol: whole-market frames carry 股票代码 and are
    filtered by it; per-symbol endpoints (解禁 queue, 分红送配) may not carry
    the column at all — their rows are taken as-is."""
    if df is None or df.empty:
        return []
    if _CODE_COL not in df.columns:
        return df.to_dict("records")
    codes = df[_CODE_COL].astype(str).str.strip().str.replace(r"\.0$", "", regex=True).str.zfill(6)
    return df.loc[codes == symbol].to_dict("records")


def _cn_preannouncement_events(
    df: pd.DataFrame | None, symbol: str, today: date
) -> list[dict[str, Any]]:
    """业绩预告 rows announcing today or later → preannouncement events."""
    events = []
    for row in _symbol_rows(df, symbol):
        when = _first_date(row, ("预约披露日期", "公告日期"))
        if when is None or when < today:
            continue
        event: dict[str, Any] = {
            "date": when.isoformat(),
            "type": "preannouncement",
            "title": "业绩预告",
        }
        indicator = str(row.get("预测指标") or "")
        hint = None
        if "每股收益" in indicator or "EPS" in indicator.upper():
            hint = _to_float(row.get("预测数值"))
        detail = _clean_detail({"eps_hint": hint})
        if detail is not None:
            event["detail"] = detail
        events.append(event)
    return events


def _cn_unlock_events(df: pd.DataFrame | None, symbol: str, today: date) -> list[dict[str, Any]]:
    """解禁 queue rows unlocking today or later → unlock events."""
    events = []
    for row in _symbol_rows(df, symbol):
        when = _first_date(row, ("解禁时间",))
        if when is None or when < today:
            continue
        shares = None
        for col in ("解禁数量", "实际解禁数量"):
            shares = _to_int(row.get(col))
            if shares is not None:
                break
        pct = None
        for col in ("占总股本比例", "占总市值比例", "占流通市值比例"):
            pct = _pct_value(row.get(col))
            if pct is not None:
                break
        event: dict[str, Any] = {
            "date": when.isoformat(),
            "type": "unlock",
            "title": "限售解禁",
        }
        detail = _clean_detail({"shares": shares, "pct_of_float": pct})
        if detail is not None:
            event["detail"] = detail
        events.append(event)
    return events


def _cn_dividend_amount(row: dict[str, Any]) -> float | None:
    """Cash dividend amount: the numeric 比例 first, the 10派N description
    as fallback (预案 rows often carry the description only)."""
    amount = _pct_value(row.get("现金分红-现金分红比例"))
    if amount is not None:
        return amount
    match = re.search(r"10派(\d+(?:\.\d+)?)", str(row.get("现金分红-现金分红比例描述") or ""))
    return _to_float(match.group(1)) if match else None


def _cn_dividend_events(df: pd.DataFrame | None, symbol: str, today: date) -> list[dict[str, Any]]:
    """分红送配 rows with an upcoming 除权除息日 / 股权登记日 → dividend events
    (a row can contribute both — record date first once sorted)."""
    events = []
    for row in (df if df is not None else pd.DataFrame()).to_dict("records"):
        detail = _clean_detail(
            {
                "amount": _cn_dividend_amount(row),
                "yield_pct": _pct_value(row.get("现金分红-股息率")),
            }
        )
        for col, title in (("除权除息日", "除息日"), ("股权登记日", "股权登记日")):
            when = _parse_date(row.get(col))
            if when is None or when < today:
                continue
            event: dict[str, Any] = {
                "date": when.isoformat(),
                "type": "dividend",
                "title": title,
            }
            if detail is not None:
                event["detail"] = detail
            events.append(event)
    return events


def _report_periods(today: date) -> list[str]:
    """Quarter-end report periods (YYYYMMDD) whose 业绩预告 windows can hold
    future-dated 公告日期: the floor (latest ended) and the ceil (in progress)
    — one call each, deduped when today is itself a quarter-end."""
    ends = [
        date(year, int(md[:2]), int(md[2:]))
        for year in (today.year - 1, today.year, today.year + 1)
        for md in _QUARTER_ENDS
    ]
    picked = set()
    past = [d for d in ends if d <= today]
    future = [d for d in ends if d >= today]
    if past:
        picked.add(max(past))
    if future:
        picked.add(min(future))
    return sorted(d.strftime("%Y%m%d") for d in picked)


def _sync_fetch_cn_event_raw(
    symbol: str, ak: Any
) -> tuple[pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None]:
    """Raw CN event frames: (业绩预告 concat, 解禁 queue, 分红送配). Each leg
    degrades alone — one dead endpoint never takes the others down."""
    pre_frames = []
    for period in _report_periods(date.today()):
        try:
            frame = ak.stock_yjyg_em(date=period)
        except Exception as e:
            logger.warning(f"[events] 业绩预告 {symbol} {period} failed: {e}")
            continue
        if frame is not None and not frame.empty:
            pre_frames.append(frame)
    pre_df = pd.concat(pre_frames, ignore_index=True) if pre_frames else None

    unlock_df = None
    try:
        unlock_df = ak.stock_restricted_release_queue_em(symbol=symbol)
    except Exception as e:
        logger.warning(f"[events] 解禁 {symbol} failed: {e}")

    div_df = None
    try:
        div_df = ak.stock_fhps_detail_em(symbol=symbol)
    except Exception as e:
        logger.warning(f"[events] 分红送配 {symbol} failed: {e}")

    return pre_df, unlock_df, div_df


def _fetch_cn_frames(
    symbol: str, akshare_module: Any = None
) -> tuple[pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None]:
    """Resolve the akshare module (injected or lazy import) and fetch the raw
    frames; module missing or fetch blowing up → all None, never raises."""
    ak = akshare_module
    if ak is None:
        try:
            import akshare as ak  # CN-only lazy import
        except ImportError:
            return None, None, None
    try:
        return _sync_fetch_cn_event_raw(symbol, ak)
    except Exception as e:
        logger.warning(f"[events] CN event fetch failed for {symbol}: {e}")
        return None, None, None


# ── Dispatch ────────────────────────────────────────────────────────


def build_event_calendar(
    symbol: str, *, ticker: Any = None, akshare_module: Any = None
) -> dict[str, Any] | None:
    """Build the event-calendar block for one symbol; None when no provider
    contributed an upcoming event (the caller then omits the key).

    6-digit symbols dispatch to the CN akshare seam; everything else (US/HK)
    to the yfinance ticker seam. Both fetch layers are dependency-injected
    so tests stay hermetic; the agent passes the real ones.
    """
    today = date.today()

    if symbol.isdigit() and len(symbol) == 6:
        pre_df, unlock_df, div_df = _fetch_cn_frames(symbol, akshare_module)
        legs = (
            (_cn_preannouncement_events, pre_df),
            (_cn_unlock_events, unlock_df),
            (_cn_dividend_events, div_df),
        )
    else:
        legs = ((_us_events, ticker),)

    events: list[dict[str, Any]] = []
    for builder, raw in legs:
        try:
            events.extend(builder(raw, symbol, today))
        except Exception as e:
            # The builders are defensive, but a bug in one must never take
            # the whole calendar down — its leg contributes nothing instead.
            logger.warning(f"[events] {builder.__name__} failed for {symbol}: {e}")

    unique: dict[tuple[str, str, str], dict[str, Any]] = {}
    for event in events:
        key = (event["date"], event["type"], event["title"])
        unique.setdefault(key, event)
    upcoming = sorted(unique.values(), key=lambda event: event["date"])[:MAX_UPCOMING_EVENTS]

    if not upcoming:
        return None
    return {"upcoming": upcoming, "as_of": today.isoformat()}
