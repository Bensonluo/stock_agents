"""Unit tests for resilience module."""

import pytest
import asyncio

from app.resilience import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerRegistry,
    CircuitState,
    RetryConfig,
    RetryHistory,
    RetryManager,
    RetryStrategy,
    TimeLimiter,
)


class TestRetryManager:
    """Tests for RetryManager class."""

    @pytest.mark.asyncio
    async def test_successful_execution(self):
        """Test successful execution without retry."""
        manager = RetryManager()

        async def test_func():
            return "success"

        result = await manager.execute_with_retry(test_func)
        assert result == "success"

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """Test retry logic on transient failure."""
        manager = RetryManager()
        attempts = []

        async def test_func():
            attempts.append(1)
            if len(attempts) < 3:
                raise ConnectionError("Transient error")
            return "success"

        result = await manager.execute_with_retry(test_func)
        assert result == "success"
        assert len(attempts) == 3

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self):
        """Test that max retries is respected."""
        config = RetryConfig(max_attempts=3)
        manager = RetryManager(default_config=config)

        async def test_func():
            raise ConnectionError("Always fails")

        with pytest.raises(ConnectionError):
            await manager.execute_with_retry(test_func)


class TestCircuitBreaker:
    """Tests for CircuitBreaker class."""

    def test_initial_state(self):
        """Test initial circuit state."""
        config = CircuitBreakerConfig(failure_threshold=5)
        breaker = CircuitBreaker("test", config)

        assert breaker.get_state() == CircuitState.CLOSED
        assert breaker.allow_request()

    def test_opens_on_threshold(self):
        """Test circuit opens after failure threshold."""
        config = CircuitBreakerConfig(failure_threshold=3)
        breaker = CircuitBreaker("test", config)

        # Record failures up to threshold
        for _ in range(3):
            breaker.record_failure("TestError")

        assert breaker.get_state() == CircuitState.OPEN
        assert not breaker.allow_request()

    def test_get_stats(self):
        """Test get_stats method."""
        config = CircuitBreakerConfig(failure_threshold=3)
        breaker = CircuitBreaker("test", config)

        breaker.record_success(1.0)
        breaker.record_failure("TestError")

        stats = breaker.get_stats()
        assert stats["name"] == "test"
        assert "total_calls" in stats


class TestCircuitBreakerRegistry:
    """Tests for CircuitBreakerRegistry class."""

    def test_get_or_create(self):
        """Test getting or creating circuit breaker."""
        registry = CircuitBreakerRegistry()

        cb1 = registry.get("test_agent")
        cb2 = registry.get("test_agent")

        assert cb1 is cb2  # Same instance

    def test_get_open_circuits(self):
        """Test getting open circuits."""
        registry = CircuitBreakerRegistry()

        open_circuits = registry.get_open_circuits()
        assert isinstance(open_circuits, list)


class TestTimeLimiter:
    """Tests for TimeLimiter class."""

    @pytest.mark.asyncio
    async def test_successful_execution(self):
        """Test successful execution within timeout."""
        limiter = TimeLimiter(default_timeout=5.0)

        async def test_func():
            return "success"

        result = await limiter.execute_with_timeout(
            test_func,
            timeout=2.0,
        )
        assert result == "success"

    @pytest.mark.asyncio
    async def test_timeout(self):
        """Test timeout enforcement."""
        limiter = TimeLimiter(default_timeout=1.0)

        async def test_func():
            await asyncio.sleep(5)
            return "success"

        with pytest.raises((asyncio.TimeoutError, TimeoutError)):
            await limiter.execute_with_timeout(
                test_func,
                timeout=0.5,
            )

    def test_get_stats(self):
        """Test getting timeout stats."""
        limiter = TimeLimiter(default_timeout=30.0)

        stats = limiter.get_all_stats()
        assert isinstance(stats, dict)
