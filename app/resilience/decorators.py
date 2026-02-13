"""Resilience decorators for fault-tolerant function execution."""

import functools
from typing import Any, Callable, Optional, TypeVar

from app.resilience.circuit_breaker import (
    CircuitBreakerRegistry,
    get_circuit_breaker_registry,
)
from app.resilience.retry import RetryConfig, RetryManager, get_retry_manager
from app.resilience.timeout import TimeLimiter, get_time_limiter
from app.utils.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


def fault_tolerant(
    name: Optional[str] = None,
    max_retries: int = 3,
    timeout: Optional[float] = None,
    circuit_breaker: bool = True,
):
    """Decorator that adds comprehensive fault tolerance to a function.

    This decorator combines:
    - Retry logic with exponential backoff
    - Timeout protection
    - Circuit breaker pattern

    Args:
        name: Optional name for tracking. Uses function name if not provided.
        max_retries: Maximum number of retry attempts
        timeout: Timeout in seconds for each attempt
        circuit_breaker: Whether to enable circuit breaker

    Returns:
        Decorated function with fault tolerance

    Example:
        @fault_tolerant(max_retries=3, timeout=30)
        async def my_function(arg1, arg2):
            return await some_operation(arg1, arg2)
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        func_name = name or func.__name__

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            retry_manager = get_retry_manager()
            time_limiter = get_time_limiter()
            circuit_registry = get_circuit_breaker_registry() if circuit_breaker else None

            # Check circuit breaker
            if circuit_registry and not circuit_registry.allow_request(func_name):
                logger.warning(f"Circuit breaker open for '{func_name}', blocking request")
                raise Exception(f"Circuit breaker is open for '{func_name}'")

            retry_config = RetryConfig(max_attempts=max_retries)

            async def protected_call() -> Any:
                # Execute with timeout
                return await time_limiter.execute_with_timeout(
                    func,
                    *args,
                    **kwargs,
                    timeout=timeout,
                    name=func_name,
                )

            try:
                # Execute with retry
                result = await retry_manager.execute_with_retry(
                    protected_call,
                    config=retry_config,
                )

                # Record success
                if circuit_registry:
                    circuit_registry.record_success(func_name)

                return result

            except Exception as e:
                # Record failure
                if circuit_registry:
                    circuit_registry.record_failure(func_name, str(e))

                logger.error(f"Function '{func_name}' failed after fault tolerance: {e}")
                raise

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            retry_manager = get_retry_manager()
            time_limiter = get_time_limiter()
            circuit_registry = get_circuit_breaker_registry() if circuit_breaker else None

            if circuit_registry and not circuit_registry.allow_request(func_name):
                logger.warning(f"Circuit breaker open for '{func_name}', blocking request")
                raise Exception(f"Circuit breaker is open for '{func_name}'")

            retry_config = RetryConfig(max_attempts=max_retries)

            def protected_call() -> Any:
                return time_limiter.execute_with_timeout_sync(
                    func,
                    *args,
                    **kwargs,
                    timeout=timeout,
                    name=func_name,
                )

            try:
                result = retry_manager.execute_with_retry_sync(
                    protected_call,
                    config=retry_config,
                )

                if circuit_registry:
                    circuit_registry.record_success(func_name)

                return result

            except Exception as e:
                if circuit_registry:
                    circuit_registry.record_failure(func_name, str(e))

                logger.error(f"Function '{func_name}' failed after fault tolerance: {e}")
                raise

        # Return appropriate wrapper based on whether function is async
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


import asyncio


def with_retry(
    max_attempts: int = 3,
    strategy: str = "exponential_backoff",
    base_delay: float = 1.0,
):
    """Decorator that adds retry logic to a function.

    Args:
        max_attempts: Maximum number of retry attempts
        strategy: Retry strategy ("exponential_backoff", "linear", "fixed")
        base_delay: Base delay in seconds

    Returns:
        Decorated function with retry logic
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            from app.resilience.retry import RetryStrategy, RetryConfig

            retry_manager = get_retry_manager()
            retry_config = RetryConfig(
                max_attempts=max_attempts,
                strategy=RetryStrategy(strategy),
                base_delay=base_delay,
            )

            return await retry_manager.execute_with_retry(
                func, *args, config=retry_config, **kwargs
            )

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            from app.resilience.retry import RetryStrategy, RetryConfig

            retry_manager = get_retry_manager()
            retry_config = RetryConfig(
                max_attempts=max_attempts,
                strategy=RetryStrategy(strategy),
                base_delay=base_delay,
            )

            return retry_manager.execute_with_retry_sync(
                func, *args, config=retry_config, **kwargs
            )

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


def with_timeout(
    timeout_seconds: float,
    name: Optional[str] = None,
):
    """Decorator that adds timeout protection to a function.

    Args:
        timeout_seconds: Timeout in seconds
        name: Optional name for tracking

    Returns:
        Decorated function with timeout protection
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            time_limiter = get_time_limiter()
            return await time_limiter.execute_with_timeout(
                func,
                *args,
                **kwargs,
                timeout=timeout_seconds,
                name=name or func.__name__,
            )

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            time_limiter = get_time_limiter()
            return time_limiter.execute_with_timeout_sync(
                func,
                *args,
                **kwargs,
                timeout=timeout_seconds,
                name=name or func.__name__,
            )

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


def with_circuit_breaker(
    failure_threshold: int = 5,
    recovery_timeout: int = 60,
    name: Optional[str] = None,
):
    """Decorator that adds circuit breaker protection to a function.

    Args:
        failure_threshold: Number of failures before opening circuit
        recovery_timeout: Seconds before trying to close circuit
        name: Optional name for the circuit breaker

    Returns:
        Decorated function with circuit breaker protection
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        func_name = name or func.__name__
        circuit_registry = get_circuit_breaker_registry()

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            if not circuit_registry.allow_request(func_name):
                raise Exception(f"Circuit breaker is open for '{func_name}'")

            try:
                result = await func(*args, **kwargs)
                circuit_registry.record_success(func_name)
                return result
            except Exception as e:
                circuit_registry.record_failure(func_name, str(e))
                raise

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            if not circuit_registry.allow_request(func_name):
                raise Exception(f"Circuit breaker is open for '{func_name}'")

            try:
                result = func(*args, **kwargs)
                circuit_registry.record_success(func_name)
                return result
            except Exception as e:
                circuit_registry.record_failure(func_name, str(e))
                raise

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator
