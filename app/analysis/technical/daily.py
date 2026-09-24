"""Daily technical engine (V2 plan §3.2.D, §5.1).

Canonical daily-bar indicators shared by the LangGraph pipeline agent and the
ReAct tools. Before V2 the same formulas lived in
``app/agents/analysis_agent.py`` and ``app/tools/analysis/technical.py`` and
had already drifted (one had SMA200, ATR and bollinger/volume signals, the
other did not); both now delegate here.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from app.analysis.technical.engine import make_evidence
from app.domain.schemas import MetricEvidence

# Below this many daily bars the daily indicators are meaningless.
MIN_DAILY_BARS = 20

# Bars older than this many calendar days mean the feed stopped updating
# (suspension, delisting, broken source) — analysis must say so, not stay
# silent. Normal gaps (weekends + holidays) stay well under it.
STALE_AFTER_DAYS = 14


def assess_freshness(
    as_of: datetime,
    *,
    now: datetime | None = None,
    stale_after_days: int = STALE_AFTER_DAYS,
) -> dict[str, Any]:
    """Classify bar age so stale feeds are visible, not silently current."""
    reference = now or datetime.now(UTC)
    age_days = (reference - as_of).days
    return {
        "as_of": as_of.date().isoformat(),
        "age_days": age_days,
        "stale": age_days > stale_after_days,
    }


def to_dataframe(hist: Mapping[str, Any]) -> pd.DataFrame:
    """Daily history dict -> OHLCV DataFrame indexed by date."""
    try:
        df = pd.DataFrame(
            {
                "open": list(hist.get("open") or []),
                "high": list(hist.get("high") or []),
                "low": list(hist.get("low") or []),
                "close": list(hist.get("close") or []),
                "volume": list(hist.get("volume") or []),
            },
            index=pd.to_datetime(list(hist.get("dates") or [])),
        )
        return df.dropna()
    except Exception:
        return pd.DataFrame()


def calculate_indicators(df: pd.DataFrame) -> dict[str, Any]:
    """Canonical daily indicators; unavailable values are None, never NaN."""
    close = df["close"]
    indicators: dict[str, Any] = {}

    for window in (20, 50, 200):
        if len(close) >= window:
            indicators[f"sma_{window}"] = round(float(close.rolling(window).mean().iloc[-1]), 6)
        else:
            indicators[f"sma_{window}"] = None

    indicators["ema_12"] = round(float(close.ewm(span=12).mean().iloc[-1]), 6)
    indicators["ema_26"] = round(float(close.ewm(span=26).mean().iloc[-1]), 6)

    indicators["rsi"] = _rsi(close, period=14)

    ema_12 = close.ewm(span=12).mean()
    ema_26 = close.ewm(span=26).mean()
    macd_line = ema_12 - ema_26
    signal_line = macd_line.ewm(span=9).mean()
    indicators["macd"] = {
        "macd": round(float(macd_line.iloc[-1]), 6),
        "signal": round(float(signal_line.iloc[-1]), 6),
        "histogram": round(float(macd_line.iloc[-1] - signal_line.iloc[-1]), 6),
    }

    sma_20 = close.rolling(20).mean()
    std_20 = close.rolling(20).std()
    upper = float(sma_20.iloc[-1] + std_20.iloc[-1] * 2)
    lower = float(sma_20.iloc[-1] - std_20.iloc[-1] * 2)
    indicators["bollinger_bands"] = {
        "upper": round(upper, 6),
        "middle": round(float(sma_20.iloc[-1]), 6),
        "lower": round(lower, 6),
        "width": (
            round((upper - lower) / float(sma_20.iloc[-1]), 6) if sma_20.iloc[-1] > 0 else None
        ),
    }

    atr = _atr(df, period=14)
    if atr is not None:
        indicators["atr"] = atr
        last_close = float(close.iloc[-1])
        indicators["atr_pct"] = round(atr / last_close * 100, 4) if last_close > 0 else None

    if "volume" in df.columns:
        volume_sma = df["volume"].rolling(20).mean().iloc[-1]
        if pd.notna(volume_sma) and volume_sma > 0:
            indicators["volume_sma_20"] = round(float(volume_sma), 2)
            indicators["volume_ratio"] = round(float(df["volume"].iloc[-1] / volume_sma), 4)

    return indicators


def _rsi(close: pd.Series, period: int = 14) -> float | None:
    """RSI(14) with Wilder smoothing — the definition charting platforms use.

    Seed: SMA of the first `period` changes, then the recursive smoothing
    avg = (prev_avg * (period-1) + x) / period. The old simple rolling
    means made RSI jumpier than any chart a user would compare against.
    """
    if len(close) <= period:
        return None
    delta = close.diff().dropna()
    if len(delta) < period:
        return None

    gain = delta.clip(lower=0.0).to_numpy()
    loss = (-delta.clip(upper=0.0)).to_numpy()

    avg_gain = float(gain[:period].mean())
    avg_loss = float(loss[:period].mean())
    for i in range(period, len(gain)):
        avg_gain = (avg_gain * (period - 1) + gain[i]) / period
        avg_loss = (avg_loss * (period - 1) + loss[i]) / period

    if avg_loss == 0:
        # All gains (or fully flat): flat has no momentum signal at all.
        return None if avg_gain == 0 else 100.0
    rs = avg_gain / avg_loss
    value = 100.0 - 100.0 / (1.0 + rs)
    return round(float(value), 4)


def _atr(df: pd.DataFrame, period: int = 14) -> float | None:
    """Average True Range; None when OHLC or warm-up is missing."""
    if len(df) <= period or not {"high", "low", "close"}.issubset(df.columns):
        return None
    high_low = df["high"] - df["low"]
    high_close = np.abs(df["high"] - df["close"].shift())
    low_close = np.abs(df["low"] - df["close"].shift())
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = true_range.rolling(period).mean().iloc[-1]
    return round(float(atr), 6) if pd.notna(atr) else None


def generate_signals(df: pd.DataFrame, indicators: dict[str, Any]) -> dict[str, str]:
    """Trend/RSI/MACD/Bollinger/volume signals from the canonical indicators."""
    signals: dict[str, str] = {}
    current_price = float(df["close"].iloc[-1])

    sma_20 = indicators.get("sma_20")
    sma_50 = indicators.get("sma_50")
    if sma_20 is not None and sma_50 is not None:
        if current_price > sma_20 > sma_50:
            signals["trend"] = "strong_bullish"
        elif current_price > sma_20:
            signals["trend"] = "bullish"
        elif current_price < sma_20 < sma_50:
            signals["trend"] = "strong_bearish"
        elif current_price < sma_20:
            signals["trend"] = "bearish"
        else:
            signals["trend"] = "neutral"

    rsi = indicators.get("rsi")
    if rsi is not None:
        if rsi > 70:
            signals["rsi"] = "overbought"
        elif rsi > 60:
            signals["rsi"] = "bullish"
        elif rsi < 30:
            signals["rsi"] = "oversold"
        elif rsi < 40:
            signals["rsi"] = "bearish"
        else:
            signals["rsi"] = "neutral"

    macd = indicators.get("macd") or {}
    if macd.get("histogram", 0) > 0:
        signals["macd"] = "bullish" if macd.get("macd", 0) > macd.get("signal", 0) else "neutral"
    elif macd:
        signals["macd"] = "bearish"

    bb = indicators.get("bollinger_bands") or {}
    if bb:
        if current_price > bb.get("upper", 0):
            signals["bollinger"] = "overbought"
        elif current_price < bb.get("lower", 0):
            signals["bollinger"] = "oversold"
        else:
            signals["bollinger"] = "neutral"

    volume_ratio = indicators.get("volume_ratio")
    if volume_ratio is not None:
        if volume_ratio > 2:
            signals["volume"] = "high"
        elif volume_ratio > 1.5:
            signals["volume"] = "above_average"
        elif volume_ratio < 0.5:
            signals["volume"] = "low"
        else:
            signals["volume"] = "normal"

    return signals


def find_support_resistance(
    df: pd.DataFrame, window: int = 20
) -> tuple[dict[str, float | None], dict[str, float | None]]:
    """Local-extrema support/resistance on the trailing ``window`` closes."""
    close = df["close"]
    recent = close.tail(window)

    local_min: list[float] = []
    local_max: list[float] = []
    for i in range(2, len(recent) - 2):
        if (
            recent.iloc[i] < recent.iloc[i - 1]
            and recent.iloc[i] < recent.iloc[i - 2]
            and recent.iloc[i] < recent.iloc[i + 1]
            and recent.iloc[i] < recent.iloc[i + 2]
        ):
            local_min.append(float(recent.iloc[i]))
        if (
            recent.iloc[i] > recent.iloc[i - 1]
            and recent.iloc[i] > recent.iloc[i - 2]
            and recent.iloc[i] > recent.iloc[i + 1]
            and recent.iloc[i] > recent.iloc[i + 2]
        ):
            local_max.append(float(recent.iloc[i]))

    current_price = float(close.iloc[-1])
    supports = sorted(level for level in local_min if level < current_price)
    resistances = sorted(level for level in local_max if level > current_price)

    support = {f"s{i + 1}": supports[-(i + 1)] for i in range(3) if len(supports) > i}
    resistance = {f"r{i + 1}": resistances[i] for i in range(3) if len(resistances) > i}
    return support, resistance


def calculate_sentiment(signals: dict[str, str], indicators: dict[str, Any]) -> dict[str, Any]:
    """Weighted signal score (-100..100) with volume confirmation."""
    score = 0

    trend = signals.get("trend", "neutral")
    if trend == "strong_bullish":
        score += 30
    elif trend == "bullish":
        score += 15
    elif trend == "bearish":
        score -= 15
    elif trend == "strong_bearish":
        score -= 30

    rsi_signal = signals.get("rsi", "neutral")
    if rsi_signal == "oversold":
        score += 20
    elif rsi_signal == "bullish":
        score += 10
    elif rsi_signal == "bearish":
        score -= 10
    elif rsi_signal == "overbought":
        score -= 20

    macd_signal = signals.get("macd", "neutral")
    if macd_signal == "bullish":
        score += 20
    elif macd_signal == "bearish":
        score -= 20

    bb_signal = signals.get("bollinger", "neutral")
    if bb_signal == "oversold":
        score += 15
    elif bb_signal == "overbought":
        score -= 15

    volume_signal = signals.get("volume", "normal")
    if volume_signal == "high" and score > 0:
        score += 15
    elif volume_signal == "high" and score < 0:
        score -= 15

    if score >= 60:
        sentiment = "strong_buy"
    elif score >= 30:
        sentiment = "buy"
    elif score >= 10:
        sentiment = "moderate_buy"
    elif score <= -60:
        sentiment = "strong_sell"
    elif score <= -30:
        sentiment = "sell"
    elif score <= -10:
        sentiment = "moderate_sell"
    else:
        sentiment = "hold"

    return {"score": score, "sentiment": sentiment, "strength": abs(score)}


def analyze_daily(
    hist: Mapping[str, Any],
    *,
    symbol: str,
    current_price: float | None = None,
    currency: str = "USD",
    source: str = "unknown",
) -> dict[str, Any]:
    """Full per-symbol daily analysis block (JSON-safe).

    Orchestrates the canonical functions above. Short histories return an
    explicit ``insufficient_data`` status instead of partial guesses.
    """
    df = to_dataframe(hist)
    if df.empty or len(df) < MIN_DAILY_BARS:
        return {
            "symbol": symbol,
            "status": "insufficient_data",
            "reason": f"only {len(df)} daily bars available (need {MIN_DAILY_BARS})",
            "indicators": {},
            "signals": {},
            "support": {},
            "resistance": {},
            "sentiment": {"score": 0, "sentiment": "hold", "strength": 0},
        }

    indicators = calculate_indicators(df)
    signals = generate_signals(df, indicators)
    support, resistance = find_support_resistance(df)
    sentiment = calculate_sentiment(signals, indicators)

    as_of = df.index[-1].to_pydatetime().replace(tzinfo=UTC)
    return {
        "symbol": symbol,
        "status": "available",
        "current_price": (
            current_price if current_price is not None else float(df["close"].iloc[-1])
        ),
        "as_of": as_of.isoformat(),
        "freshness": assess_freshness(as_of),
        "indicators": indicators,
        "signals": signals,
        "support": support,
        "resistance": resistance,
        "sentiment": sentiment,
        "evidence": _key_evidence(
            df, indicators, symbol=symbol, currency=currency, source=source, as_of=as_of
        ),
    }


def _key_evidence(
    df: pd.DataFrame,
    indicators: dict[str, Any],
    *,
    symbol: str,
    currency: str,
    source: str,
    as_of: datetime,
) -> list[dict[str, Any]]:
    """MetricEvidence for the headline daily numbers (SMA lines, RSI, ATR%)."""
    evidence: list[MetricEvidence] = []
    for window in (20, 50, 200):
        value = indicators.get(f"sma_{window}")
        if value is None:
            continue
        evidence.append(
            make_evidence(
                symbol=symbol,
                name=f"sma_daily_{window}",
                value=value,
                unit=currency,
                cutoff=as_of,
                source=source,
                formula=f"mean(daily_close, {window})",
                params={"window": window, "frequency": "1d"},
                sample_count=int(len(df)),
            )
        )
    rsi = indicators.get("rsi")
    if rsi is not None:
        evidence.append(
            make_evidence(
                symbol=symbol,
                name="rsi_daily_14",
                value=rsi,
                unit="index",
                cutoff=as_of,
                source=source,
                formula="rsi(daily_close, 14)",
                params={"period": 14},
            )
        )
    atr_pct = indicators.get("atr_pct")
    if atr_pct is not None:
        evidence.append(
            make_evidence(
                symbol=symbol,
                name="atr_pct_daily_14",
                value=atr_pct,
                unit="percent",
                cutoff=as_of,
                source=source,
                formula="atr(ohlc, 14) / close * 100",
                params={"period": 14},
            )
        )
    return [item.model_dump(mode="json") for item in evidence]
