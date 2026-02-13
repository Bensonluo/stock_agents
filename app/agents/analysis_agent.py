"""Analysis agent for technical and fundamental analysis."""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.agents.base import BaseAgent
from app.orchestration.state import AgentState
from app.utils.logging import get_logger

logger = get_logger(__name__)


class TechnicalAnalysisAgent(BaseAgent):
    """Agent responsible for technical analysis of stock data.

    This agent:
    - Calculates technical indicators (MA, EMA, RSI, MACD, Bollinger Bands)
    - Identifies chart patterns
    - Generates trading signals based on technical analysis
    - Provides support and resistance levels

    Uses pandas-ta for comprehensive indicator calculations.
    """

    async def execute(self, state: AgentState) -> Dict[str, Any]:
        """Execute the technical analysis agent.

        Args:
            state: Current agent state

        Returns:
            Partial state with technical analysis results only
        """
        market_data = state.get("market_data", {})

        if not market_data:
            logger.warning("No market data available for technical analysis")
            return {"technical_analysis": {}}

        logger.info(f"Performing technical analysis for {len(market_data)} symbols")

        results = {}

        for symbol, data in market_data.items():
            try:
                analysis = await self._analyze_symbol(symbol, data)
                if analysis:
                    results[symbol] = analysis
            except Exception as e:
                logger.error(f"Error analyzing {symbol}: {e}")

        logger.info(f"Completed technical analysis for {len(results)} symbols")

        # Return only the partial state (field we modify)
        return {"technical_analysis": results}

    async def _analyze_symbol(self, symbol: str, data: Dict) -> Dict[str, Any]:
        """Perform technical analysis for a single symbol.

        Args:
            symbol: Stock symbol
            data: Market data dictionary

        Returns:
            Dictionary containing technical analysis results
        """
        hist_data = data.get("historical_data")
        if not hist_data:
            return {}

        # Convert to DataFrame
        df = self._historical_data_to_dataframe(hist_data)
        if df.empty or len(df) < 20:
            logger.warning(f"Insufficient data for {symbol}")
            return {}

        # Calculate indicators
        indicators = self._calculate_indicators(df)

        # Generate signals
        signals = self._generate_signals(df, indicators)

        # Find support and resistance
        support, resistance = self._find_support_resistance(df)

        # Detect patterns
        patterns = self._detect_patterns(df)

        # Calculate overall sentiment
        sentiment = self._calculate_technical_sentiment(signals, indicators)

        return {
            "symbol": symbol,
            "current_price": data.get("current_price"),
            "indicators": indicators,
            "signals": signals,
            "support": support,
            "resistance": resistance,
            "patterns": patterns,
            "sentiment": sentiment,
            "timestamp": datetime.now().isoformat(),
        }

    def _historical_data_to_dataframe(self, hist_data: Dict) -> pd.DataFrame:
        """Convert historical data dict to DataFrame.

        Args:
            hist_data: Historical data dictionary

        Returns:
            DataFrame with OHLCV data
        """
        try:
            df = pd.DataFrame({
                "open": hist_data.get("open", []),
                "high": hist_data.get("high", []),
                "low": hist_data.get("low", []),
                "close": hist_data.get("close", []),
                "volume": hist_data.get("volume", []),
            }, index=pd.to_datetime(hist_data.get("dates", [])))

            return df.dropna()
        except Exception:
            return pd.DataFrame()

    def _calculate_indicators(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Calculate technical indicators.

        Args:
            df: Price DataFrame

        Returns:
            Dictionary of indicator values
        """
        indicators = {}

        try:
            close = df["close"]

            # Moving averages
            indicators["sma_20"] = float(close.rolling(20).mean().iloc[-1])
            indicators["sma_50"] = float(close.rolling(50).mean().iloc[-1])
            indicators["sma_200"] = float(close.rolling(200).mean().iloc[-1])

            # Exponential moving averages
            indicators["ema_12"] = float(close.ewm(span=12).mean().iloc[-1])
            indicators["ema_26"] = float(close.ewm(span=26).mean().iloc[-1])

            # RSI
            rsi = self._calculate_rsi(close)
            indicators["rsi"] = float(rsi.iloc[-1]) if not rsi.empty else None

            # MACD
            ema_12 = close.ewm(span=12).mean()
            ema_26 = close.ewm(span=26).mean()
            macd_line = ema_12 - ema_26
            signal_line = macd_line.ewm(span=9).mean()
            histogram = macd_line - signal_line

            indicators["macd"] = {
                "macd": float(macd_line.iloc[-1]),
                "signal": float(signal_line.iloc[-1]),
                "histogram": float(histogram.iloc[-1]),
            }

            # Bollinger Bands
            sma_20 = close.rolling(20).mean()
            std_20 = close.rolling(20).std()
            upper_band = sma_20 + (std_20 * 2)
            lower_band = sma_20 - (std_20 * 2)

            indicators["bollinger_bands"] = {
                "upper": float(upper_band.iloc[-1]),
                "middle": float(sma_20.iloc[-1]),
                "lower": float(lower_band.iloc[-1]),
                "width": float(
                    (upper_band.iloc[-1] - lower_band.iloc[-1]) / sma_20.iloc[-1]
                ) if sma_20.iloc[-1] > 0 else None,
            }

            # ATR (Average True Range)
            indicators["atr"] = float(self._calculate_atr(df).iloc[-1])

            # Volume indicators
            if "volume" in df.columns:
                indicators["volume_sma_20"] = float(
                    df["volume"].rolling(20).mean().iloc[-1]
                )
                indicators["volume_ratio"] = float(
                    df["volume"].iloc[-1] / df["volume"].rolling(20).mean().iloc[-1]
                ) if df["volume"].rolling(20).mean().iloc[-1] > 0 else None

        except Exception as e:
            logger.error(f"Error calculating indicators: {e}")

        return indicators

    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI indicator.

        Args:
            prices: Price series
            period: RSI period

        Returns:
            RSI values
        """
        delta = prices.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)

        avg_gain = gain.rolling(period).mean()
        avg_loss = loss.rolling(period).mean()

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return rsi

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate Average True Range.

        Args:
            df: Price DataFrame with OHLC
            period: ATR period

        Returns:
            ATR values
        """
        high_low = df["high"] - df["low"]
        high_close = np.abs(df["high"] - df["close"].shift())
        low_close = np.abs(df["low"] - df["close"].shift())

        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = true_range.rolling(period).mean()

        return atr

    def _generate_signals(
        self, df: pd.DataFrame, indicators: Dict[str, Any]
    ) -> Dict[str, str]:
        """Generate trading signals based on indicators.

        Args:
            df: Price DataFrame
            indicators: Calculated indicators

        Returns:
            Dictionary of signal categories
        """
        signals = {}
        current_price = df["close"].iloc[-1]

        # Trend signals
        sma_20 = indicators.get("sma_20")
        sma_50 = indicators.get("sma_50")

        if sma_20 and sma_50:
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

        # RSI signals
        rsi = indicators.get("rsi")
        if rsi:
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

        # MACD signals
        macd = indicators.get("macd", {})
        if macd:
            if macd.get("histogram", 0) > 0:
                if macd.get("macd", 0) > macd.get("signal", 0):
                    signals["macd"] = "bullish"
                else:
                    signals["macd"] = "neutral"
            else:
                signals["macd"] = "bearish"

        # Bollinger Band signals
        bb = indicators.get("bollinger_bands", {})
        if bb:
            if current_price > bb.get("upper", 0):
                signals["bollinger"] = "overbought"
            elif current_price < bb.get("lower", 0):
                signals["bollinger"] = "oversold"
            else:
                signals["bollinger"] = "neutral"

        # Volume signals
        vol_ratio = indicators.get("volume_ratio")
        if vol_ratio:
            if vol_ratio > 2:
                signals["volume"] = "high"
            elif vol_ratio > 1.5:
                signals["volume"] = "above_average"
            elif vol_ratio < 0.5:
                signals["volume"] = "low"
            else:
                signals["volume"] = "normal"

        return signals

    def _find_support_resistance(
        self, df: pd.DataFrame, window: int = 20
    ) -> Tuple[Dict[str, float], Dict[str, float]]:
        """Find support and resistance levels.

        Args:
            df: Price DataFrame
            window: Lookback window

        Returns:
            Tuple of (support levels, resistance levels)
        """
        close = df["close"]
        recent = close.tail(window)

        # Find local minima and maxima
        local_min = []
        local_max = []

        for i in range(2, len(recent) - 2):
            if (
                recent.iloc[i] < recent.iloc[i - 1]
                and recent.iloc[i] < recent.iloc[i - 2]
                and recent.iloc[i] < recent.iloc[i + 1]
                and recent.iloc[i] < recent.iloc[i + 2]
            ):
                local_min.append(recent.iloc[i])

            if (
                recent.iloc[i] > recent.iloc[i - 1]
                and recent.iloc[i] > recent.iloc[i - 2]
                and recent.iloc[i] > recent.iloc[i + 1]
                and recent.iloc[i] > recent.iloc[i + 2]
            ):
                local_max.append(recent.iloc[i])

        # Get closest levels
        current_price = close.iloc[-1]

        support_levels = sorted([l for l in local_min if l < current_price], reverse=True)
        resistance_levels = sorted([l for l in local_max if l > current_price])

        support = {
            "s1": float(support_levels[0]) if len(support_levels) > 0 else None,
            "s2": float(support_levels[1]) if len(support_levels) > 1 else None,
            "s3": float(support_levels[2]) if len(support_levels) > 2 else None,
        }

        resistance = {
            "r1": float(resistance_levels[0]) if len(resistance_levels) > 0 else None,
            "r2": float(resistance_levels[1]) if len(resistance_levels) > 1 else None,
            "r3": float(resistance_levels[2]) if len(resistance_levels) > 2 else None,
        }

        return support, resistance

    def _detect_patterns(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Detect common candlestick patterns.

        Args:
            df: Price DataFrame

        Returns:
            Dictionary of detected patterns
        """
        patterns = {}

        if len(df) < 3:
            return patterns

        # Get recent candles
        recent = df.tail(5).to_dict("records")

        # Simple pattern detection
        latest = recent[-1]
        prev = recent[-2]

        # Doji (open ≈ close)
        body_size = abs(latest["close"] - latest["open"])
        range_size = latest["high"] - latest["low"]
        if range_size > 0 and body_size / range_size < 0.1:
            patterns["doji"] = True

        # Hammer (small body, long lower shadow)
        lower_shadow = latest["close"] - latest["low"] if latest["close"] > latest["open"] else latest["open"] - latest["low"]
        upper_shadow = latest["high"] - max(latest["open"], latest["close"])
        if lower_shadow > body_size * 2 and upper_shadow < body_size * 0.5:
            patterns["hammer"] = True

        # Engulfing patterns
        prev_body = abs(prev["close"] - prev["open"])
        curr_body = abs(latest["close"] - latest["open"])

        if curr_body > prev_body * 1.2:
            if (
                prev["close"] > prev["open"]  # Previous was bullish
                and latest["close"] < latest["open"]  # Current is bearish
                and latest["open"] > prev["close"]
                and latest["close"] < prev["open"]
            ):
                patterns["bearish_engulfing"] = True

            elif (
                prev["close"] < prev["open"]  # Previous was bearish
                and latest["close"] > latest["open"]  # Current is bullish
                and latest["open"] < prev["close"]
                and latest["close"] > prev["open"]
            ):
                patterns["bullish_engulfing"] = True

        return patterns

    def _calculate_technical_sentiment(
        self, signals: Dict[str, str], indicators: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Calculate overall technical sentiment.

        Args:
            signals: Trading signals
            indicators: Technical indicators

        Returns:
            Sentiment analysis with score
        """
        score = 0  # Range: -100 (bearish) to +100 (bullish)

        # Trend contribution (30%)
        trend = signals.get("trend", "neutral")
        if trend == "strong_bullish":
            score += 30
        elif trend == "bullish":
            score += 15
        elif trend == "bearish":
            score -= 15
        elif trend == "strong_bearish":
            score -= 30

        # RSI contribution (20%)
        rsi_signal = signals.get("rsi", "neutral")
        if rsi_signal == "oversold":
            score += 20  # Oversold is bullish signal
        elif rsi_signal == "bullish":
            score += 10
        elif rsi_signal == "bearish":
            score -= 10
        elif rsi_signal == "overbought":
            score -= 20  # Overbought is bearish signal

        # MACD contribution (20%)
        macd_signal = signals.get("macd", "neutral")
        if macd_signal == "bullish":
            score += 20
        elif macd_signal == "bearish":
            score -= 20

        # Bollinger Bands contribution (15%)
        bb_signal = signals.get("bollinger", "neutral")
        if bb_signal == "oversold":
            score += 15
        elif bb_signal == "overbought":
            score -= 15

        # Volume contribution (15%)
        vol_signal = signals.get("volume", "normal")
        if vol_signal == "high" and score > 0:
            score += 15  # High volume confirms bullish trend
        elif vol_signal == "high" and score < 0:
            score -= 15  # High volume confirms bearish trend

        # Determine sentiment label
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

        return {
            "score": score,
            "sentiment": sentiment,
            "strength": abs(score),
        }


class FundamentalAnalysisAgent(BaseAgent):
    """Agent responsible for fundamental analysis of stocks.

    This agent:
    - Analyzes financial statements
    - Calculates valuation metrics
    - Compares with industry averages
    - Evaluates financial health
    - Assesses growth potential
    """

    async def execute(self, state: AgentState) -> Dict[str, Any]:
        """Execute the fundamental analysis agent.

        Args:
            state: Current agent state

        Returns:
            Partial state with fundamental analysis results only
        """
        financial_data = state.get("financial_data", {})
        market_data = state.get("market_data", {})

        if not financial_data:
            logger.warning("No financial data available for fundamental analysis")
            return {"fundamental_analysis": {}}

        logger.info(f"Performing fundamental analysis for {len(financial_data)} symbols")

        results = {}

        for symbol in financial_data:
            try:
                fin_data = financial_data.get(symbol, {})
                mkt_data = market_data.get(symbol, {})

                analysis = await self._analyze_fundamentals(symbol, fin_data, mkt_data)
                if analysis:
                    results[symbol] = analysis
            except Exception as e:
                logger.error(f"Error analyzing fundamentals for {symbol}: {e}")

        logger.info(f"Completed fundamental analysis for {len(results)} symbols")

        # Return only the partial state (field we modify)
        return {"fundamental_analysis": results}

    async def _analyze_fundamentals(
        self, symbol: str, fin_data: Dict, mkt_data: Dict
    ) -> Dict[str, Any]:
        """Perform fundamental analysis for a single symbol.

        Args:
            symbol: Stock symbol
            fin_data: Financial data dictionary
            mkt_data: Market data dictionary

        Returns:
            Dictionary containing fundamental analysis results
        """
        metrics = fin_data.get("metrics", {})

        # Analyze profitability
        profitability = self._analyze_profitability(metrics)

        # Analyze valuation
        valuation = self._analyze_valuation(metrics, mkt_data)

        # Analyze financial health
        health = self._analyze_financial_health(metrics)

        # Analyze growth
        growth = self._analyze_growth(fin_data)

        # Calculate overall score
        overall_score = self._calculate_overall_score(
            profitability, valuation, health, growth
        )

        # Generate recommendation
        recommendation = self._generate_recommendation(overall_score)

        return {
            "symbol": symbol,
            "profitability": profitability,
            "valuation": valuation,
            "financial_health": health,
            "growth": growth,
            "overall_score": overall_score,
            "recommendation": recommendation,
            "timestamp": datetime.now().isoformat(),
        }

    def _analyze_profitability(self, metrics: Dict) -> Dict[str, Any]:
        """Analyze profitability metrics.

        Args:
            metrics: Financial metrics dictionary

        Returns:
            Profitability analysis
        """
        roe = metrics.get("roe")
        roa = metrics.get("roa")
        profit_margin = metrics.get("profit_margin")
        operating_margin = metrics.get("operating_margin")

        score = 0
        details = {}

        # ROE analysis (0-40 points)
        if roe:
            details["roe"] = float(roe)
            if roe >= 20:
                score += 40
            elif roe >= 15:
                score += 30
            elif roe >= 10:
                score += 20
            elif roe >= 5:
                score += 10

        # ROA analysis (0-20 points)
        if roa:
            details["roa"] = float(roa)
            if roa >= 10:
                score += 20
            elif roa >= 5:
                score += 15
            elif roa >= 2:
                score += 10

        # Profit margin analysis (0-20 points)
        if profit_margin:
            details["profit_margin"] = float(profit_margin)
            if profit_margin >= 0.2:
                score += 20
            elif profit_margin >= 0.1:
                score += 15
            elif profit_margin >= 0.05:
                score += 10

        # Operating margin analysis (0-20 points)
        if operating_margin:
            details["operating_margin"] = float(operating_margin)
            if operating_margin >= 0.15:
                score += 20
            elif operating_margin >= 0.1:
                score += 15
            elif operating_margin >= 0.05:
                score += 10

        return {
            "score": score,
            "rating": self._score_to_rating(score, 100),
            "details": details,
        }

    def _analyze_valuation(self, metrics: Dict, mkt_data: Dict) -> Dict[str, Any]:
        """Analyze valuation metrics.

        Args:
            metrics: Financial metrics dictionary
            mkt_data: Market data dictionary

        Returns:
            Valuation analysis
        """
        pe = metrics.get("pe_ratio")
        pb = metrics.get("pb_ratio")
        ps = metrics.get("ps_ratio")
        ev_ebitda = metrics.get("ev_ebitda")

        score = 0
        details = {}

        # P/E analysis (0-30 points)
        if pe:
            details["pe_ratio"] = float(pe)
            if 0 < pe <= 15:
                score += 30  # Undervalued
            elif pe <= 25:
                score += 20  # Fair value
            elif pe <= 40:
                score += 10  # Slightly overvalued

        # P/B analysis (0-25 points)
        if pb:
            details["pb_ratio"] = float(pb)
            if 0 < pb <= 1:
                score += 25
            elif pb <= 2:
                score += 20
            elif pb <= 3:
                score += 15

        # P/S analysis (0-25 points)
        if ps:
            details["ps_ratio"] = float(ps)
            if 0 < ps <= 2:
                score += 25
            elif ps <= 4:
                score += 20
            elif ps <= 6:
                score += 15

        # EV/EBITDA analysis (0-20 points)
        if ev_ebitda:
            details["ev_ebitda"] = float(ev_ebitda)
            if 0 < ev_ebitda <= 8:
                score += 20
            elif ev_ebitda <= 12:
                score += 15
            elif ev_ebitda <= 16:
                score += 10

        return {
            "score": score,
            "rating": self._score_to_rating(score, 100),
            "details": details,
        }

    def _analyze_financial_health(self, metrics: Dict) -> Dict[str, Any]:
        """Analyze financial health metrics.

        Args:
            metrics: Financial metrics dictionary

        Returns:
            Financial health analysis
        """
        debt_to_equity = metrics.get("debt_to_equity")
        current_ratio = metrics.get("current_ratio")
        quick_ratio = metrics.get("quick_ratio")

        score = 0
        details = {}

        # Debt-to-equity analysis (0-40 points)
        if debt_to_equity is not None:
            details["debt_to_equity"] = float(debt_to_equity)
            if 0 <= debt_to_equity <= 0.5:
                score += 40
            elif debt_to_equity <= 1:
                score += 30
            elif debt_to_equity <= 1.5:
                score += 20
            elif debt_to_equity <= 2:
                score += 10

        # Current ratio analysis (0-30 points)
        if current_ratio:
            details["current_ratio"] = float(current_ratio)
            if current_ratio >= 2:
                score += 30
            elif current_ratio >= 1.5:
                score += 25
            elif current_ratio >= 1:
                score += 15

        # Quick ratio analysis (0-30 points)
        if quick_ratio:
            details["quick_ratio"] = float(quick_ratio)
            if quick_ratio >= 1.5:
                score += 30
            elif quick_ratio >= 1:
                score += 25
            elif quick_ratio >= 0.8:
                score += 15

        return {
            "score": score,
            "rating": self._score_to_rating(score, 100),
            "details": details,
        }

    def _analyze_growth(self, fin_data: Dict) -> Dict[str, Any]:
        """Analyze growth metrics.

        Args:
            fin_data: Financial data dictionary

        Returns:
            Growth analysis
        """
        # This would require historical financial data
        # For now, return a placeholder
        return {
            "score": 50,
            "rating": "neutral",
            "details": {
                "note": "Growth analysis requires historical data comparison"
            }
        }

    def _calculate_overall_score(
        self,
        profitability: Dict,
        valuation: Dict,
        health: Dict,
        growth: Dict,
    ) -> Dict[str, Any]:
        """Calculate overall fundamental score.

        Args:
            profitability: Profitability analysis
            valuation: Valuation analysis
            health: Financial health analysis
            growth: Growth analysis

        Returns:
            Overall score and rating
        """
        # Weighted average
        # Profitability: 35%
        # Valuation: 30%
        # Health: 25%
        # Growth: 10%

        p_score = profitability.get("score", 0)
        v_score = valuation.get("score", 0)
        h_score = health.get("score", 0)
        g_score = growth.get("score", 0)

        overall = (
            p_score * 0.35 +
            v_score * 0.30 +
            h_score * 0.25 +
            g_score * 0.10
        )

        return {
            "score": round(overall, 2),
            "components": {
                "profitability": p_score,
                "valuation": v_score,
                "health": h_score,
                "growth": g_score,
            },
            "rating": self._score_to_rating(overall, 100),
        }

    def _generate_recommendation(self, overall_score: Dict) -> str:
        """Generate investment recommendation.

        Args:
            overall_score: Overall score dictionary

        Returns:
            Recommendation string
        """
        score = overall_score.get("score", 50)

        if score >= 75:
            return "strong_buy"
        elif score >= 60:
            return "buy"
        elif score >= 45:
            return "hold"
        elif score >= 30:
            return "sell"
        else:
            return "strong_sell"

    def _score_to_rating(self, score: float, max_score: float) -> str:
        """Convert score to rating.

        Args:
            score: Actual score
            max_score: Maximum possible score

        Returns:
            Rating string
        """
        percentage = score / max_score if max_score > 0 else 0

        if percentage >= 0.8:
            return "excellent"
        elif percentage >= 0.6:
            return "good"
        elif percentage >= 0.4:
            return "fair"
        elif percentage >= 0.2:
            return "poor"
        else:
            return "very_poor"
