"""Application configuration management."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str = "postgresql://admin:password@localhost:5432/stockdb"
    redis_url: str = "redis://localhost:6379"

    # Checkpoint persistence: auto | sqlite | postgres | memory
    # auto = postgres when DATABASE_URL is explicitly set, else durable sqlite
    checkpoint_backend: str = "auto"
    checkpoint_db_path: str = "data/checkpoints.db"

    # API Keys
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    zhipuai_api_key: str | None = None
    tushare_token: str | None = None
    alpha_vantage_key: str | None = None
    finnhub_api_key: str | None = None

    # JWT
    jwt_secret: str = "change-this-secret-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiration: int = 86400  # 24 hours

    # Application
    app_name: str = "Stock Analysis Multi-Agent System"
    app_version: str = "0.1.0"
    debug: bool = False
    log_level: str = "INFO"

    # Agent Settings
    max_retries: int = 3
    timeout_per_agent: int = 300
    parallel_execution: bool = True

    # Decision layer: blend dimension weights toward measured IC once every
    # directional dimension clears the evidence gates (runs + dispersion).
    # False = the fixed 45/30/15 blend, always.
    ic_adaptive_weights_enabled: bool = True

    # Monitoring
    enable_metrics: bool = True
    metrics_port: int = 9090
    alert_success_rate_threshold: float = 0.95
    alert_health_score_threshold: float = 70.0
    alert_execution_time_threshold: float = 30.0

    # Circuit Breaker
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_timeout: int = 300  # 5 minutes

    # CORS
    frontend_url: str = "http://localhost:3000"
    allowed_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:8000",
    ]

    # LLM Settings
    primary_llm_model: str = "glm-5.3-flash"  # fast tier for analysis
    secondary_llm_model: str = "glm-5.3-flash"
    batch_llm_model: str = "glm-5.3-flash"
    llm_temperature: float = 0.3
    llm_max_tokens: int = 4096
    llm_timeout: int = 60
    # Optional LLM narrative overlay on the pipeline report (bounded, degrades to None)
    report_llm_enabled: bool = False
    report_llm_timeout: float = 60.0
    # LLM semantic per-article news scoring (keyword scorer stays the floor)
    llm_sentiment_enabled: bool = False
    # Jensen's alpha risk-free rate (annualized, cash T-bill level; alpha only)
    risk_free_rate_annual: float = 0.04
    # Liquidity floors for the risk annotation: 20-day average daily traded
    # value below this flags exit-liquidity risk (per source currency).
    min_adv_usd: float = 2_000_000
    min_adv_cny: float = 20_000_000
    # Eval harness: LLM-as-judge opt-in (deterministic rubric is always on in tests)
    eval_llm_judge: bool = False

    # Data Sources
    akshare_enabled: bool = True
    yfinance_enabled: bool = True
    finnhub_enabled: bool = True
    cache_ttl: int = 300  # 5 minutes

    # Agent Settings (ReAct)
    agent_max_iterations: int = 15
    agent_cost_limit: float = 0.50  # USD
    agent_reasoning_model: str = "glm-5.3-flash"

    # Backtesting
    backtest_initial_cash: float = 10000.0
    backtest_commission: float = 0.001


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Global settings instance
settings = get_settings()
