"""Auto-fetching analysis tools that only require a symbol parameter.

These wrap the existing analysis functions but automatically fetch data
from the multi-source fetcher, so the LLM only needs to pass a symbol string.
"""

import asyncio
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.tools.analysis.fundamental import (
    _analyze_financial_health,
    _analyze_profitability,
    _analyze_valuation,
    _recommendation,
    _score_to_rating,
)
from app.tools.analysis.sentiment import (
    NEGATIVE_WORDS,
    POSITIVE_WORDS,
    _calculate_overall,
    _calculate_trend,
    _empty_sentiment,
)
from app.tools.analysis.technical import (
    _calculate_indicators,
    _calculate_sentiment,
    _find_support_resistance,
    _generate_signals,
    _to_dataframe,
)
from app.tools.data.fetcher import fetch_stock_data, fetch_historical
from app.utils.logging import get_logger

logger = get_logger(__name__)


async def _fetch_and_split(symbol: str) -> dict[str, Any] | None:
    """Fetch stock data and split into components.

    Tries both fetch_stock_data (snapshot) and fetch_historical (OHLC series).
    If the snapshot's historical_data is empty, supplements it from fetch_historical.
    """
    data = await fetch_stock_data(symbol)
    if not data:
        return None

    market = data.get("market_data", {}) or {}
    hist_block = market.get("historical_data") or {}

    # If snapshot didn't include historical (e.g. Finnhub free tier / yfinance 429),
    # pull the OHLC series from fetch_historical and merge it in.
    if not hist_block.get("dates"):
        try:
            hist = await fetch_historical(symbol, period="3mo")
            if isinstance(hist, dict) and hist.get("dates") and "error" not in hist:
                market["historical_data"] = {
                    "dates": hist["dates"],
                    "open": hist.get("open", []),
                    "high": hist.get("high", []),
                    "low": hist.get("low", []),
                    "close": hist.get("close", []),
                    "volume": hist.get("volume", []),
                }
        except Exception as e:
            logger.warning(f"[auto_tools] historical fetch fallback failed for {symbol}: {e}")

    return {
        "market_data": {symbol: market},
        "financial_data": {symbol: data.get("financial_data", {})},
        "news_data": data.get("news_data", []),
    }


class AnalyzeTechnicalSimpleInput(BaseModel):
    symbol: str = Field(description="Stock symbol to analyze (e.g., 'AAPL', '600000')")


@tool(args_schema=AnalyzeTechnicalSimpleInput)
async def analyze_technical(symbol: str) -> dict[str, Any]:
    """Compute technical indicators (RSI, MACD, Bollinger Bands, support/resistance).
    Automatically fetches the latest market data.
    """
    data = await _fetch_and_split(symbol)
    if not data:
        return {"error": f"Could not fetch data for {symbol}"}

    market = data["market_data"].get(symbol, {})
    hist = market.get("historical_data")
    if not hist:
        return {"error": f"No historical data for {symbol}"}

    try:
        df = _to_dataframe(hist)
        if df.empty or len(df) < 20:
            return {"error": f"Insufficient data points for {symbol} ({len(df)} rows)"}

        indicators = _calculate_indicators(df)
        signals = _generate_signals(df, indicators)
        support, resistance = _find_support_resistance(df)
        sentiment = _calculate_sentiment(signals, indicators)

        return {
            "symbol": symbol,
            "current_price": market.get("current_price"),
            "indicators": indicators,
            "signals": signals,
            "support": support,
            "resistance": resistance,
            "sentiment": sentiment,
        }
    except Exception as e:
        logger.error(f"Technical analysis failed for {symbol}: {e}")
        return {"error": f"Technical analysis failed: {e}"}


class AnalyzeFundamentalSimpleInput(BaseModel):
    symbol: str = Field(description="Stock symbol to analyze (e.g., 'AAPL', '600000')")


@tool(args_schema=AnalyzeFundamentalSimpleInput)
async def analyze_fundamental(symbol: str) -> dict[str, Any]:
    """Evaluate financial health, profitability, and valuation (PE, PB, ROE, etc.).
    Automatically fetches the latest financial data.
    """
    data = await _fetch_and_split(symbol)
    if not data:
        return {"error": f"Could not fetch data for {symbol}"}

    financial = data["financial_data"].get(symbol, {})
    mkt = data["market_data"].get(symbol, {})
    metrics = financial.get("metrics", {})

    profitability = _analyze_profitability(metrics)
    valuation = _analyze_valuation(metrics, mkt)
    health = _analyze_financial_health(metrics)
    p_score = profitability["score"]
    v_score = valuation["score"]
    h_score = health["score"]
    overall = p_score * 0.35 + v_score * 0.30 + h_score * 0.25 + 50 * 0.10

    return {
        "symbol": symbol,
        "profitability": profitability,
        "valuation": valuation,
        "financial_health": health,
        "overall_score": {"score": round(overall, 2), "rating": _score_to_rating(overall, 100)},
        "recommendation": _recommendation(overall),
    }


class AnalyzeSentimentSimpleInput(BaseModel):
    symbol: str = Field(description="Stock symbol to analyze")


@tool(args_schema=AnalyzeSentimentSimpleInput)
async def analyze_sentiment(symbol: str) -> dict[str, Any]:
    """Assess market sentiment from recent news for a stock.
    Automatically fetches the latest news data.
    """
    data = await _fetch_and_split(symbol)
    if not data:
        return {"error": f"Could not fetch data for {symbol}"}

    news_data = data["news_data"]
    if not news_data:
        return {"symbol": symbol, "sentiment_by_symbol": {symbol: _empty_sentiment()},
                "overall_sentiment": {"sentiment": "neutral", "score": 0, "note": "No news available"}}

    symbol_news = [
        n for n in news_data
        if symbol in n.get("related_symbols", []) or n.get("original_symbol") == symbol
        or symbol.lower() in (n.get("title", "") + n.get("summary", "")).lower()
    ]
    if not symbol_news:
        symbol_news = news_data

    total_score, analyzed, recent_scores = 0, 0, []
    for article in symbol_news:
        text = (article.get("title", "") + " " + article.get("summary", "")).lower()
        score = sum(1 for w in POSITIVE_WORDS if w in text) - sum(1 for w in NEGATIVE_WORDS if w in text)
        if score != 0:
            total_score += score
            analyzed += 1
            recent_scores.append(score)

    normalized = max(-100, min(100, (total_score / analyzed) * 20)) if analyzed > 0 else 0
    if normalized >= 40:
        sentiment = "very_positive"
    elif normalized >= 15:
        sentiment = "positive"
    elif normalized <= -40:
        sentiment = "very_negative"
    elif normalized <= -15:
        sentiment = "negative"
    else:
        sentiment = "neutral"

    result = {
        "sentiment": sentiment,
        "score": normalized,
        "article_count": analyzed,
        "recent_scores": recent_scores[-10:],
        "trend": _calculate_trend(recent_scores),
    }

    return {
        "symbol": symbol,
        "sentiment": result,
        "overall_sentiment": _calculate_overall({symbol: result}),
        "headlines": [n.get("title", "") for n in symbol_news[:5]],
    }


class AssessRiskSimpleInput(BaseModel):
    symbol: str = Field(description="Stock symbol to assess risk for")


@tool(args_schema=AssessRiskSimpleInput)
async def assess_risk(symbol: str) -> dict[str, Any]:
    """Calculate risk metrics (volatility, VaR, max drawdown, risk score).
    Automatically fetches the latest market data.
    """
    import numpy as np
    from app.tools.risk.assessment import (
        _calculate_score,
        _downside_risk,
        _max_drawdown,
        _position_size,
        _score_to_level,
        _warnings,
    )

    data = await _fetch_and_split(symbol)
    if not data:
        return {"error": f"Could not fetch data for {symbol}"}

    market = data["market_data"].get(symbol, {})
    hist = market.get("historical_data", {})
    closes = np.array(hist.get("close", []))

    if len(closes) < 20:
        return {
            "symbol": symbol, "risk_score": 50, "risk_level": "medium",
            "metrics": {}, "note": "Insufficient data for detailed risk assessment",
        }

    returns = np.diff(closes) / closes[:-1]
    volatility = float(np.std(returns))
    var_95 = float(np.percentile(returns, 5))
    var_99 = float(np.percentile(returns, 1))
    max_dd = _max_drawdown(closes)
    downside = _downside_risk(returns)
    risk_score = _calculate_score(volatility, max_dd, var_95, 1.0)
    risk_level = _score_to_level(risk_score)

    return {
        "symbol": symbol,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "metrics": {
            "volatility": volatility,
            "volatility_annualized": float(volatility * np.sqrt(252)),
            "var_95": var_95,
            "var_99": var_99,
            "max_drawdown": max_dd,
            "downside_risk": downside,
        },
        "position_recommendation": {
            "max_position_size": _position_size(risk_score),
            "stop_loss_percentage": float(volatility * 2 * 100),
        },
        "warnings": _warnings(risk_level, volatility, max_dd),
    }


class GetStockOverviewInput(BaseModel):
    symbol: str = Field(description="Stock symbol (e.g., 'AAPL', '600000')")


@tool(args_schema=GetStockOverviewInput)
async def get_stock_overview(symbol: str) -> dict[str, Any]:
    """Get a quick stock overview: company name, current price, change,
    sector, market cap, 52-week range. Use this to fill in the
    market_summary section of a report.
    """
    data = await fetch_stock_data(symbol)
    if not data:
        return {"error": f"Could not fetch data for {symbol}"}
    m = data.get("market_data", {})
    return {
        "symbol": symbol,
        "company_name": m.get("company_name"),
        "current_price": m.get("current_price"),
        "change": m.get("change"),
        "change_percent": m.get("change_percent"),
        "volume": m.get("volume"),
        "market_cap": m.get("market_cap"),
        "sector": m.get("sector"),
        "currency": m.get("currency"),
        "exchange": m.get("exchange"),
        "52_week_high": m.get("52_week_high"),
        "52_week_low": m.get("52_week_low"),
    }
