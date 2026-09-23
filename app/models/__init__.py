"""Data models for the application."""

from datetime import datetime

from pydantic import BaseModel, Field, validator


class StockQuote(BaseModel):
    """Stock quote model."""

    symbol: str
    name: str | None = None
    price: float | None = None
    change: float | None = None
    change_percent: float | None = None
    volume: int | None = None
    market_cap: int | None = None
    high_52_week: float | None = None
    low_52_week: float | None = None
    timestamp: str

    @validator("symbol")
    def normalize_symbol(cls, v):
        """Normalize symbol to uppercase."""
        return v.upper()


class TechnicalIndicators(BaseModel):
    """Technical indicators model."""

    symbol: str
    sma_20: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    rsi: float | None = None
    macd: dict | None = None
    bollinger_bands: dict | None = None
    timestamp: str


class FundamentalMetrics(BaseModel):
    """Fundamental metrics model."""

    symbol: str
    pe_ratio: float | None = None
    pb_ratio: float | None = None
    roe: float | None = None
    roa: float | None = None
    debt_to_equity: float | None = None
    current_ratio: float | None = None
    profit_margin: float | None = None
    dividend_yield: float | None = None
    timestamp: str


class RiskMetrics(BaseModel):
    """Risk metrics model."""

    symbol: str
    volatility: float | None = None
    var_95: float | None = None
    max_drawdown: float | None = None
    beta: float | None = None
    risk_score: int | None = None
    risk_level: str | None = None
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
    technical_analysis: dict | None = None
    fundamental_analysis: dict | None = None
    sentiment_analysis: dict | None = None
    risk_assessment: dict | None = None
    decisions: dict | None = None
    report: dict | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class BacktestRequest(BaseModel):
    """Backtest request model."""

    symbol: str
    strategy: str
    start_date: str
    end_date: str
    initial_cash: float = 10000
    commission: float = 0.001
    strategy_params: dict | None = None


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
