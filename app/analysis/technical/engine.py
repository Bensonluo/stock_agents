"""Deterministic technical engine (V2 plan §3.2.D, §5.1).

Single source of truth for weekly trend features. Both the LangGraph pipeline
and the ReAct agent must call this engine instead of re-implementing formulas.

The engine computes the five weekly SMA groups (5/10/20/40/60 weeks) with the
metadata the V2 methodology requires per line: current value, distance from
price, 4/12-week slopes, consecutive weeks above/below, neighbouring crosses
with return and volume confirmation, and warm-up status. Every numeric output
is also emitted as :class:`~app.domain.schemas.MetricEvidence`; warm-up gaps
surface as ``insufficient_data`` evidence with ``value=None`` — never NaN and
never a neutral filler number.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from app.domain.schemas import (
    DataQuality,
    MetricEvidence,
    MetricQuality,
    build_metric_id,
)

# Interpretable default grid covering ~1 month to >1 year of trend (V2 plan
# §3.2.D). Not a "proven optimal" parameter set; configurable per market.
WEEKLY_SMA_WINDOWS: tuple[int, ...] = (5, 10, 20, 40, 60)

# Below this many weekly bars nothing can be said about weekly trend at all.
MIN_WEEKLY_BARS = 5


def resample_weekly(
    dates: list[str], close: list[float], volume: list[float] | None = None
) -> pd.DataFrame:
    """Resample daily bars to week-ending-Friday bars.

    Close is the last daily close of the week; volume is the weekly sum. The
    final week may be partial (week not finished yet) and is kept — callers
    comparing across weeks should treat the last bar as provisional.
    """
    index = pd.DatetimeIndex(pd.to_datetime(dates)).sort_values()
    closes = pd.Series(close, index=index, dtype="float64").groupby(level=0).last()
    data = {"close": closes}
    agg = {"close": "last"}
    if volume is not None:
        data["volume"] = pd.Series(volume, index=index, dtype="float64").groupby(level=0).sum()
        agg["volume"] = "sum"
    return pd.DataFrame(data).resample("W-FRI").agg(agg).dropna(subset=["close"])


def weekly_sma_pack(
    daily_history: Mapping[str, Any],
    *,
    symbol: str,
    as_of: datetime | None = None,
    currency: str = "USD",
    source: str = "unknown",
) -> dict[str, Any]:
    """Compute the weekly SMA evidence pack for one symbol.

    Args:
        daily_history: ``{"dates": [...], "close": [...], "volume": [...]?}``
            daily bars, ideally >= 3 years for the 60-week line.
        symbol: Symbol the history belongs to (used in evidence ids).
        as_of: Data cutoff stamped onto the evidence; defaults to the last bar.
        currency: Unit for price-like evidence values.
        source: Provider name stamped onto the evidence.

    Returns:
        A dict with ``status``, per-window SMA details, alignment state and
        ``evidence`` (list of MetricEvidence).
    """
    dates = list(daily_history.get("dates") or [])
    close = list(daily_history.get("close") or [])
    raw_volume = daily_history.get("volume")
    volume = list(raw_volume) if raw_volume is not None else None

    if not dates or len(dates) != len(close):
        return _insufficient_pack(symbol, as_of, reason="daily history empty or malformed")

    weekly = resample_weekly(dates, close, volume)
    if len(weekly) < MIN_WEEKLY_BARS:
        return _insufficient_pack(
            symbol, as_of, reason=f"only {len(weekly)} weekly bars available"
        )

    cutoff = as_of or weekly.index[-1].to_pydatetime().replace(tzinfo=UTC)
    last_close = float(weekly["close"].iloc[-1])

    sma_series: dict[int, pd.Series] = {}
    sma_details: dict[str, Any] = {}
    evidence: list[MetricEvidence] = []

    for window in WEEKLY_SMA_WINDOWS:
        series = weekly["close"].rolling(window).mean()
        sma_series[window] = series
        value = series.iloc[-1]
        warm_up_met = len(weekly) >= window and pd.notna(value)
        name = f"sma_weekly_{window}"

        if not warm_up_met:
            sma_details[str(window)] = {
                "window_weeks": window,
                "warm_up_met": False,
                "sample_count": int(series.notna().sum()),
                "value": None,
                "status": "insufficient_data",
                "required_weeks": window,
            }
            evidence.append(
                _evidence(
                    symbol=symbol,
                    name=name,
                    value=None,
                    unit=currency,
                    cutoff=cutoff,
                    source=source,
                    formula=f"mean(weekly_close, {window})",
                    params={"window": window, "frequency": "1wk"},
                    sample_count=int(series.notna().sum()),
                    quality=MetricQuality.INSUFFICIENT_DATA,
                )
            )
            continue

        sma_value = round(float(value), 6)
        above = (weekly["close"] >= series) & series.notna()
        details: dict[str, Any] = {
            "window_weeks": window,
            "warm_up_met": True,
            "sample_count": int(series.notna().sum()),
            "value": sma_value,
            "unit": currency,
            "distance_pct": round((last_close - sma_value) / sma_value * 100, 4),
            "weeks_above" if bool(above.iloc[-1]) else "weeks_below": _consecutive_weeks(above),
            "slope_4w_pct": _slope_pct(series, 4),
            "slope_12w_pct": _slope_pct(series, 12),
        }
        sma_details[str(window)] = details

        evidence.append(
            _evidence(
                symbol=symbol,
                name=name,
                value=sma_value,
                unit=currency,
                cutoff=cutoff,
                source=source,
                formula=f"mean(weekly_close, {window})",
                params={"window": window, "frequency": "1wk"},
                sample_count=details["sample_count"],
            )
        )
        for horizon in (4, 12):
            slope = details[f"slope_{horizon}w_pct"]
            if slope is not None:
                evidence.append(
                    _evidence(
                        symbol=symbol,
                        name=f"{name}_slope_{horizon}w_pct",
                        value=slope,
                        unit="percent",
                        cutoff=cutoff,
                        source=source,
                        formula=f"pct_change(mean(weekly_close, {window}), {horizon}w)",
                        params={"window": window, "horizon_weeks": horizon},
                    )
                )

    crosses = {
        f"{a}_vs_{b}": _latest_cross(sma_series[a], sma_series[b], weekly)
        for a, b in zip(WEEKLY_SMA_WINDOWS, WEEKLY_SMA_WINDOWS[1:])
    }
    alignment = _alignment(weekly, sma_series)
    warm_count = sum(1 for detail in sma_details.values() if detail["warm_up_met"])

    quality = DataQuality(
        as_of=cutoff,
        symbols=[symbol],
        coverage={symbol: warm_count / len(WEEKLY_SMA_WINDOWS)},
    )

    return {
        "symbol": symbol,
        "status": "available" if warm_count == len(WEEKLY_SMA_WINDOWS) else "partial",
        "frequency": "1wk",
        "as_of": cutoff.isoformat(),
        "last_close": round(last_close, 6),
        "weekly_bars": int(len(weekly)),
        "first_week": weekly.index[0].date().isoformat(),
        "last_week": weekly.index[-1].date().isoformat(),
        "sma": sma_details,
        "alignment": alignment,
        "crosses": crosses,
        "data_quality": quality,
        "evidence": evidence,
    }


def weekly_sma_summary(
    daily_history: Mapping[str, Any],
    *,
    symbol: str,
    as_of: datetime | None = None,
    currency: str = "USD",
    source: str = "unknown",
    include_evidence: bool = True,
) -> dict[str, Any]:
    """JSON-serializable weekly SMA pack for agent and tool outputs.

    Same computation as :func:`weekly_sma_pack`, but evidence and data quality
    are pre-serialized so the result can flow through orchestrator state, API
    responses and LLM tool output without pydantic objects leaking. Pass
    ``include_evidence=False`` for contexts where token budget matters (ReAct
    tool output) — the per-line numbers stay, only the evidence list drops.
    """
    pack = weekly_sma_pack(
        daily_history,
        symbol=symbol,
        as_of=as_of,
        currency=currency,
        source=source,
    )
    summary = {key: value for key, value in pack.items() if key not in ("data_quality", "evidence")}
    summary["data_quality"] = pack["data_quality"].model_dump(mode="json")
    if include_evidence:
        summary["evidence"] = [item.model_dump(mode="json") for item in pack["evidence"]]
    return summary


def compact_weekly_view(pack: Mapping[str, Any] | None) -> dict[str, Any]:
    """Compact consumption view of a weekly SMA pack for reports and LLM prompts.

    Reports only need the trend verdict, alignment persistence and how far
    price sits from each line — not the full evidence trail.
    """
    if not isinstance(pack, Mapping) or pack.get("status") in (None, "error", "unavailable"):
        return {"status": "unavailable"}
    status = str(pack.get("status"))
    if status == "insufficient_data":
        return {"status": status, "reason": pack.get("reason")}

    alignment = pack.get("alignment") or {}
    view: dict[str, Any] = {
        "status": status,
        "as_of": pack.get("as_of"),
        "alignment": {
            "state": alignment.get("state"),
            "weeks_in_state": alignment.get("weeks_in_state"),
        },
        "sma_distance_pct": {
            str(window): detail.get("distance_pct")
            for window, detail in (pack.get("sma") or {}).items()
            if detail.get("warm_up_met")
        },
    }
    recent_crosses = {
        pair: {"direction": cross.get("direction"), "weeks_since": cross.get("weeks_since")}
        for pair, cross in (pack.get("crosses") or {}).items()
        if cross.get("status") == "observed"
    }
    if recent_crosses:
        view["recent_crosses"] = recent_crosses
    return view


def _insufficient_pack(symbol: str, as_of: datetime | None, *, reason: str) -> dict[str, Any]:
    cutoff = as_of or datetime.now(UTC)
    return {
        "symbol": symbol,
        "status": "insufficient_data",
        "reason": reason,
        "as_of": cutoff.isoformat(),
        "sma": {},
        "alignment": {"state": "unknown"},
        "crosses": {},
        "data_quality": DataQuality(as_of=cutoff, symbols=[symbol], coverage={symbol: 0.0}),
        "evidence": [],
    }


def _evidence(
    *,
    symbol: str,
    name: str,
    value: float | None,
    unit: str,
    cutoff: datetime,
    source: str,
    formula: str,
    params: dict[str, Any],
    sample_count: int | None = None,
    quality: MetricQuality = MetricQuality.VERIFIED,
) -> MetricEvidence:
    return MetricEvidence(
        metric_id=build_metric_id(symbol, "technical", name, cutoff.date()),
        name=name,
        value=value,
        unit=unit,
        as_of=cutoff,
        source=source,
        formula=formula,
        params=params,
        sample_count=sample_count,
        quality=quality,
    )


def _slope_pct(series: pd.Series, weeks: int) -> float | None:
    """Percent change of the SMA over the trailing ``weeks`` weeks."""
    if len(series) <= weeks:
        return None
    current, past = series.iloc[-1], series.iloc[-1 - weeks]
    if pd.isna(current) or pd.isna(past) or past == 0:
        return None
    return round((current - past) / abs(past) * 100, 4)


def _consecutive_weeks(condition: pd.Series) -> int:
    """Weeks ``condition`` held consecutively up to the last bar."""
    count = 0
    for held in condition.iloc[::-1]:
        if not held:
            break
        count += 1
    return count


def _latest_cross(fast: pd.Series, slow: pd.Series, weekly: pd.DataFrame) -> dict[str, Any]:
    """Most recent sign change of ``fast - slow`` with return/volume context."""
    diff = (fast - slow).dropna()
    if len(diff) < 2:
        return {"status": "insufficient_data"}

    last_diff = diff.iloc[-1]
    cross_ts = None
    for offset in range(len(diff) - 1, 0, -1):
        if (diff.iloc[offset] >= 0) != (diff.iloc[offset - 1] >= 0):
            cross_ts = diff.index[offset]
            break

    if cross_ts is None:
        return {
            "status": "no_cross_observed",
            "relation": "fast_above" if last_diff > 0 else "fast_below",
        }

    weeks_since = len(diff.loc[cross_ts:]) - 1
    close_at_cross = float(weekly["close"].loc[cross_ts])
    return_since_pct = round((weekly["close"].iloc[-1] / close_at_cross - 1) * 100, 4)

    volume_confirmation = None
    if "volume" in weekly:
        after = weekly["volume"].loc[cross_ts:]
        before = weekly["volume"].loc[:cross_ts].iloc[-len(after) :]
        if len(before) and before.sum() > 0:
            volume_confirmation = bool(after.mean() >= before.mean())

    return {
        "status": "observed",
        "cross_date": cross_ts.date().isoformat(),
        "weeks_since": int(weeks_since),
        "direction": "golden" if last_diff > 0 else "death",
        "return_since_pct": return_since_pct,
        "volume_confirmation": volume_confirmation,
    }


def _alignment(weekly: pd.DataFrame, sma_series: dict[int, pd.Series]) -> dict[str, Any]:
    """Multi-line alignment (bullish/bearish/mixed) and weeks in that state."""
    last_values = [series.iloc[-1] for series in sma_series.values()]
    if any(pd.isna(value) for value in last_values):
        return {"state": "insufficient_data"}

    closes = weekly["close"]
    duration = 0
    state: str | None = None
    for position in range(len(weekly) - 1, -1, -1):
        row_chain = [closes.iloc[position]] + [
            sma_series[window].iloc[position] for window in WEEKLY_SMA_WINDOWS
        ]
        if any(pd.isna(value) for value in row_chain):
            break
        if all(a > b for a, b in zip(row_chain, row_chain[1:])):
            row_state = "bullish"
        elif all(a < b for a, b in zip(row_chain, row_chain[1:])):
            row_state = "bearish"
        else:
            row_state = "mixed"
        if state is None:
            state = row_state
        elif row_state != state:
            break
        duration += 1

    return {
        "state": state or "insufficient_data",
        "weeks_in_state": duration,
        "lines_compared": len(WEEKLY_SMA_WINDOWS) + 1,
    }
