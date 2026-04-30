"""Application configuration management."""

from functools import lru_cache
from typing import Optional

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

    # API Keys
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    zhipuai_api_key: Optional[str] = None
    tushare_token: Optional[str] = None
    alpha_vantage_key: Optional[str] = None

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
    primary_llm_model: str = "glm-4.7"  # GLM-4.7 for complex tasks
    secondary_llm_model: str = "glm-4.5-air"  # GLM-4.5-Air for faster responses
    batch_llm_model: str = "glm-4.5-air"  # GLM-4.5-Air for batch operations
    llm_temperature: float = 0.3
    llm_max_tokens: int = 2000
    llm_timeout: int = 60

    # Agent Settings (ReAct)
    agent_max_iterations: int = 15
    agent_cost_limit: float = 0.50  # USD
    agent_reasoning_model: str = "glm-4.7"
    agent_reflection_model: str = "glm-4.5-air"

    # Data Sources
    akshare_enabled: bool = True
    yfinance_enabled: bool = True
    cache_ttl: int = 300  # 5 minutes

    # Backtesting
    backtest_initial_cash: float = 10000.0
    backtest_commission: float = 0.001


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Global settings instance
settings = get_settings()
