"""Technical analysis tools. Extracted from app/agents/analysis_agent.py"""

from typing import Any, Tuple

import numpy as np
import pandas as pd
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.utils.logging import get_logger

logger = get_logger(__name__)


class AnalyzeTechnicalInput(BaseModel):
    market_data: dict = Field(description="Market data from fetch_stock_data")


@tool(args_schema=AnalyzeTechnicalInput)
def analyze_technical(market_data: dict) -> dict[str, Any]:
    """Compute technical indicators (RSI, MACD, Bollinger Bands, support/resistance)."""
    results = {}

    for symbol, data in market_data.items():
        hist = data.get("historical_data")
        if not hist:
            continue
        try:
            df = _to_dataframe(hist)
            if df.empty or len(df) < 20:
                continue
            indicators = _calculate_indicators(df)
            signals = _generate_signals(df, indicators)
            support, resistance = _find_support_resistance(df)
            sentiment = _calculate_sentiment(signals, indicators)
            results[symbol] = {
                "symbol": symbol,
                "current_price": data.get("current_price"),
                "indicators": indicators,
                "signals": signals,
                "support": support,
                "resistance": resistance,
                "sentiment": sentiment,
            }
        except Exception as e:
            logger.error(f"Technical analysis failed for {symbol}: {e}")

    return results


def _to_dataframe(hist: dict) -> pd.DataFrame:
    df = pd.DataFrame({
        "open": hist.get("open", []),
        "high": hist.get("high", []),
        "low": hist.get("low", []),
        "close": hist.get("close", []),
        "volume": hist.get("volume", []),
    }, index=pd.to_datetime(hist.get("dates", [])))
    return df.dropna()


def _calculate_indicators(df: pd.DataFrame) -> dict:
    close = df["close"]
    indicators = {}
    indicators["sma_20"] = float(close.rolling(20).mean().iloc[-1])
    indicators["sma_50"] = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
    indicators["ema_12"] = float(close.ewm(span=12).mean().iloc[-1])
    indicators["ema_26"] = float(close.ewm(span=26).mean().iloc[-1])

    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    indicators["rsi"] = float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else None

    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9).mean()
    indicators["macd"] = {
        "macd": float(macd_line.iloc[-1]),
        "signal": float(signal_line.iloc[-1]),
        "histogram": float(macd_line.iloc[-1] - signal_line.iloc[-1]),
    }

    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    indicators["bollinger_bands"] = {
        "upper": float(sma20.iloc[-1] + std20.iloc[-1] * 2),
        "middle": float(sma20.iloc[-1]),
        "lower": float(sma20.iloc[-1] - std20.iloc[-1] * 2),
    }

    return indicators


def _generate_signals(df: pd.DataFrame, indicators: dict) -> dict:
    signals = {}
    current = df["close"].iloc[-1]
    sma20 = indicators.get("sma_20")
    sma50 = indicators.get("sma_50")

    if sma20 and sma50:
        if current > sma20 > sma50:
            signals["trend"] = "strong_bullish"
        elif current > sma20:
            signals["trend"] = "bullish"
        elif current < sma20 < sma50:
            signals["trend"] = "strong_bearish"
        elif current < sma20:
            signals["trend"] = "bearish"
        else:
            signals["trend"] = "neutral"

    rsi = indicators.get("rsi")
    if rsi:
        if rsi > 70: signals["rsi"] = "overbought"
        elif rsi > 60: signals["rsi"] = "bullish"
        elif rsi < 30: signals["rsi"] = "oversold"
        elif rsi < 40: signals["rsi"] = "bearish"
        else: signals["rsi"] = "neutral"

    macd = indicators.get("macd", {})
    if macd.get("histogram", 0) > 0:
        signals["macd"] = "bullish" if macd.get("macd", 0) > macd.get("signal", 0) else "neutral"
    else:
        signals["macd"] = "bearish"

    return signals


def _find_support_resistance(df: pd.DataFrame, window: int = 20) -> Tuple[dict, dict]:
    close = df["close"]
    recent = close.tail(window)
    local_min, local_max = [], []
    for i in range(2, len(recent) - 2):
        if (recent.iloc[i] < recent.iloc[i-1] and recent.iloc[i] < recent.iloc[i-2] and
            recent.iloc[i] < recent.iloc[i+1] and recent.iloc[i] < recent.iloc[i+2]):
            local_min.append(recent.iloc[i])
        if (recent.iloc[i] > recent.iloc[i-1] and recent.iloc[i] > recent.iloc[i-2] and
            recent.iloc[i] > recent.iloc[i+1] and recent.iloc[i] > recent.iloc[i+2]):
            local_max.append(recent.iloc[i])
    current = close.iloc[-1]
    support = sorted([l for l in local_min if l < current], reverse=True)
    resistance = sorted([l for l in local_max if l > current])
    return (
        {"s1": float(support[0]) if support else None, "s2": float(support[1]) if len(support) > 1 else None},
        {"r1": float(resistance[0]) if resistance else None, "r2": float(resistance[1]) if len(resistance) > 1 else None},
    )


def _calculate_sentiment(signals: dict, indicators: dict) -> dict:
    score = 0
    trend = signals.get("trend", "neutral")
    if trend == "strong_bullish": score += 30
    elif trend == "bullish": score += 15
    elif trend == "bearish": score -= 15
    elif trend == "strong_bearish": score -= 30
    rsi = signals.get("rsi", "neutral")
    if rsi == "oversold": score += 20
    elif rsi == "bullish": score += 10
    elif rsi == "bearish": score -= 10
    elif rsi == "overbought": score -= 20
    macd = signals.get("macd", "neutral")
    if macd == "bullish": score += 20
    elif macd == "bearish": score -= 20

    if score >= 60: sentiment = "strong_buy"
    elif score >= 30: sentiment = "buy"
    elif score >= 10: sentiment = "moderate_buy"
    elif score <= -60: sentiment = "strong_sell"
    elif score <= -30: sentiment = "sell"
    elif score <= -10: sentiment = "moderate_sell"
    else: sentiment = "hold"

    return {"score": score, "sentiment": sentiment, "strength": abs(score)}
