"""Resilience module for fault-tolerant execution."""

from app.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerRegistry,
    CircuitState,
    get_circuit_breaker_registry,
    reset_circuit_breaker_registry,
)
from app.resilience.decorators import (
    fault_tolerant,
    with_circuit_breaker,
    with_retry,
    with_timeout,
)
from app.resilience.retry import (
    RetryConfig,
    RetryHistory,
    RetryManager,
    RetryStrategy,
    get_retry_manager,
    reset_retry_manager,
)
from app.resilience.timeout import (
    TimeLimiter,
    TimeoutResult,
    TimeoutStats,
    get_time_limiter,
    reset_time_limiter,
)

__all__ = [
    # Circuit Breaker
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerRegistry",
    "CircuitState",
    "get_circuit_breaker_registry",
    "reset_circuit_breaker_registry",
    # Retry
    "RetryConfig",
    "RetryHistory",
    "RetryManager",
    "RetryStrategy",
    "get_retry_manager",
    "reset_retry_manager",
    # Timeout
    "TimeLimiter",
    "TimeoutResult",
    "TimeoutStats",
    "get_time_limiter",
    "reset_time_limiter",
    # Decorators
    "fault_tolerant",
    "with_retry",
    "with_timeout",
    "with_circuit_breaker",
]
