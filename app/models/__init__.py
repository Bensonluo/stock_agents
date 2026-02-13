"""Data models for the application."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, validator


class StockQuote(BaseModel):
    """Stock quote model."""

    symbol: str
    name: Optional[str] = None
    price: Optional[float] = None
    change: Optional[float] = None
    change_percent: Optional[float] = None
    volume: Optional[int] = None
    market_cap: Optional[int] = None
    high_52_week: Optional[float] = None
    low_52_week: Optional[float] = None
    timestamp: str

    @validator("symbol")
    def normalize_symbol(cls, v):
        """Normalize symbol to uppercase."""
        return v.upper()


class TechnicalIndicators(BaseModel):
    """Technical indicators model."""

    symbol: str
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    sma_200: Optional[float] = None
    rsi: Optional[float] = None
    macd: Optional[dict] = None
    bollinger_bands: Optional[dict] = None
    timestamp: str


class FundamentalMetrics(BaseModel):
    """Fundamental metrics model."""

    symbol: str
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    roe: Optional[float] = None
    roa: Optional[float] = None
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    profit_margin: Optional[float] = None
    dividend_yield: Optional[float] = None
    timestamp: str


class RiskMetrics(BaseModel):
    """Risk metrics model."""

    symbol: str
    volatility: Optional[float] = None
    var_95: Optional[float] = None
    max_drawdown: Optional[float] = None
    beta: Optional[float] = None
    risk_score: Optional[int] = None
    risk_level: Optional[str] = None
    timestamp: str


class AnalysisRequest(BaseModel):
    """Analysis request model."""

    query: str
    symbols: list[str]

    @validator("symbols", each_item=True)
    def validate_symbols(cls, v):
        """Validate symbols."""
        if not v or len(v) == 0:
            raise ValueError("symbol cannot be empty")
        return v.upper()


class AnalysisResponse(BaseModel):
    """Analysis response model."""

    thread_id: str
    status: str
    query: str
    symbols: list[str]
    technical_analysis: Optional[dict] = None
    fundamental_analysis: Optional[dict] = None
    sentiment_analysis: Optional[dict] = None
    risk_assessment: Optional[dict] = None
    decisions: Optional[dict] = None
    report: Optional[dict] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class BacktestRequest(BaseModel):
    """Backtest request model."""

    symbol: str
    strategy: str
    start_date: str
    end_date: str
    initial_cash: float = 10000
    commission: float = 0.001
    strategy_params: Optional[dict] = None


class BacktestResponse(BaseModel):
    """Backtest response model."""

    symbol: str
    strategy: str
    period_start: str
    period_end: str
    initial_cash: float
    final_value: float
    total_return: float
    total_return_pct: float
    annual_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    total_trades: int
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
