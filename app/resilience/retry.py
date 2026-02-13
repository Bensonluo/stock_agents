"""Retry mechanism for handling transient failures."""

import asyncio
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TypeVar

from app.utils.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class RetryStrategy(Enum):
    """Retry strategy enumeration."""

    EXPONENTIAL_BACKOFF = "exponential_backoff"
    LINEAR_BACKOFF = "linear_backoff"
    FIXED_DELAY = "fixed_delay"
    IMMEDIATE = "immediate"


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_attempts: int = 3
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL_BACKOFF
    base_delay: float = 1.0  # Base delay in seconds
    max_delay: float = 60.0  # Maximum delay in seconds
    multiplier: float = 2.0  # For exponential backoff
    jitter: bool = True  # Add randomness to delay
    jitter_factor: float = 0.1  # Jitter as fraction of delay

    # Retryable error types
    retryable_exceptions: List[str] = field(default_factory=lambda: [
        "TimeoutError",
        "ConnectionError",
        "RateLimitError",
        "TemporaryFailure",
        "HTTPError",
        "RequestException",
    ])


@dataclass
class RetryAttempt:
    """Record of a single retry attempt."""

    attempt_number: int
    started_at: datetime
    completed_at: Optional[datetime] = None
    success: bool = False
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    delay_before: float = 0.0


@dataclass
class RetryHistory:
    """Complete history of a retry operation."""

    retry_id: str
    function_name: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    attempts: List[RetryAttempt] = field(default_factory=list)
    success: bool = False
    total_delay: float = 0.0

    def add_attempt(self, attempt: RetryAttempt) -> None:
        """Add an attempt to the history."""
        self.attempts.append(attempt)
        self.total_delay += attempt.delay_before

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the retry history."""
        return {
            "retry_id": self.retry_id,
            "function_name": self.function_name,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "success": self.success,
            "total_attempts": len(self.attempts),
            "total_delay": self.total_delay,
            "attempts": [
                {
                    "attempt": a.attempt_number,
                    "success": a.success,
                    "error_type": a.error_type,
                    "delay_before": a.delay_before,
                }
                for a in self.attempts
            ],
        }


class RetryManager:
    """Manages retry logic for transient failures.

    This class provides:
    - Multiple retry strategies (exponential backoff, linear, fixed)
    - Jitter for thundering herd prevention
    - Retry history tracking
    - Configurable retryable exceptions

    Core learning: Implementing retry patterns for distributed systems resilience.
    """

    def __init__(self, default_config: Optional[RetryConfig] = None):
        """Initialize the retry manager.

        Args:
            default_config: Default retry configuration
        """
        self.default_config = default_config or RetryConfig()
        self.history: List[RetryHistory] = []

    async def execute_with_retry(
        self,
        func: Callable[..., T],
        *args: Any,
        config: Optional[RetryConfig] = None,
        **kwargs: Any,
    ) -> T:
        """Execute a function with retry logic.

        Args:
            func: Function to execute
            *args: Positional arguments for the function
            config: Retry configuration (uses default if not provided)
            **kwargs: Keyword arguments for the function

        Returns:
            Result from the function

        Raises:
            Last exception if all retries are exhausted
        """
        config = config or self.default_config
        retry_id = str(uuid.uuid4())
        history = RetryHistory(
            retry_id=retry_id,
            function_name=func.__name__,
            started_at=datetime.now(),
        )

        last_exception = None

        for attempt in range(1, config.max_attempts + 1):
            # Calculate delay before this attempt
            delay = self._calculate_delay(attempt, config)

            attempt_record = RetryAttempt(
                attempt_number=attempt,
                started_at=datetime.now(),
                delay_before=delay,
            )

            # Wait before retrying (except for first attempt)
            if attempt > 1 and delay > 0:
                logger.debug(
                    f"Retry attempt {attempt}/{config.max_attempts} "
                    f"for {func.__name__} after {delay:.2f}s delay"
                )
                await asyncio.sleep(delay)

            try:
                # Execute the function
                result = await func(*args, **kwargs)

                attempt_record.completed_at = datetime.now()
                attempt_record.success = True

                history.add_attempt(attempt_record)
                history.success = True
                history.completed_at = datetime.now()

                self.history.append(history)

                logger.debug(
                    f"Function {func.__name__} succeeded on attempt {attempt}/{config.max_attempts}"
                )

                return result

            except Exception as e:
                last_exception = e
                error_type = type(e).__name__

                attempt_record.completed_at = datetime.now()
                attempt_record.success = False
                attempt_record.error_type = error_type
                attempt_record.error_message = str(e)

                history.add_attempt(attempt_record)

                # Check if error is retryable
                is_retryable = self._is_retryable_error(error_type, config)

                if not is_retryable or attempt >= config.max_attempts:
                    # Don't retry or max attempts reached
                    history.success = False
                    history.completed_at = datetime.now()
                    self.history.append(history)

                    logger.warning(
                        f"Function {func.__name__} failed after {attempt} attempts: {error_type}"
                    )

                    raise

                logger.debug(
                    f"Function {func.__name__} failed on attempt {attempt}/{config.max_attempts}: "
                    f"{error_type} - retryable"
                )

        # Should not reach here, but just in case
        if last_exception:
            raise last_exception

    def execute_with_retry_sync(
        self,
        func: Callable[..., T],
        *args: Any,
        config: Optional[RetryConfig] = None,
        **kwargs: Any,
    ) -> T:
        """Execute a synchronous function with retry logic.

        Args:
            func: Function to execute
            *args: Positional arguments for the function
            config: Retry configuration (uses default if not provided)
            **kwargs: Keyword arguments for the function

        Returns:
            Result from the function

        Raises:
            Last exception if all retries are exhausted
        """
        import time

        config = config or self.default_config
        retry_id = str(uuid.uuid4())
        history = RetryHistory(
            retry_id=retry_id,
            function_name=func.__name__,
            started_at=datetime.now(),
        )

        last_exception = None

        for attempt in range(1, config.max_attempts + 1):
            delay = self._calculate_delay(attempt, config)

            attempt_record = RetryAttempt(
                attempt_number=attempt,
                started_at=datetime.now(),
                delay_before=delay,
            )

            if attempt > 1 and delay > 0:
                logger.debug(
                    f"Retry attempt {attempt}/{config.max_attempts} "
                    f"for {func.__name__} after {delay:.2f}s delay"
                )
                time.sleep(delay)

            try:
                result = func(*args, **kwargs)

                attempt_record.completed_at = datetime.now()
                attempt_record.success = True

                history.add_attempt(attempt_record)
                history.success = True
                history.completed_at = datetime.now()

                self.history.append(history)

                return result

            except Exception as e:
                last_exception = e
                error_type = type(e).__name__

                attempt_record.completed_at = datetime.now()
                attempt_record.success = False
                attempt_record.error_type = error_type
                attempt_record.error_message = str(e)

                history.add_attempt(attempt_record)

                is_retryable = self._is_retryable_error(error_type, config)

                if not is_retryable or attempt >= config.max_attempts:
                    history.success = False
                    history.completed_at = datetime.now()
                    self.history.append(history)
                    raise

        if last_exception:
            raise last_exception

    def get_retry_history(
        self,
        function_name: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get retry history.

        Args:
            function_name: Optional filter by function name
            limit: Maximum number of records to return

        Returns:
            List of retry history summaries
        """
        history = self.history

        if function_name:
            history = [h for h in history if h.function_name == function_name]

        # Get most recent
        history = history[-limit:]

        return [h.get_summary() for h in reversed(history)]

    def get_retry_statistics(self) -> Dict[str, Any]:
        """Get statistics about retry operations.

        Returns:
            Dictionary containing retry statistics
        """
        if not self.history:
            return {
                "total_retries": 0,
                "successful_retries": 0,
                "failed_retries": 0,
                "avg_attempts": 0.0,
                "total_delay": 0.0,
            }

        successful = [h for h in self.history if h.success]
        failed = [h for h in self.history if not h.success]

        total_attempts = sum(len(h.attempts) for h in self.history)
        total_delay = sum(h.total_delay for h in self.history)

        return {
            "total_retries": len(self.history),
            "successful_retries": len(successful),
            "failed_retries": len(failed),
            "success_rate": len(successful) / len(self.history),
            "avg_attempts": total_attempts / len(self.history),
            "total_delay": total_delay,
            "avg_delay": total_delay / len(self.history),
        }

    def clear_history(self, older_than: Optional[int] = None) -> None:
        """Clear retry history.

        Args:
            older_than: Optional age in seconds. If provided, only clears
                records older than this value.
        """
        if older_than is None:
            self.history.clear()
        else:
            cutoff = datetime.now().timestamp() - older_than
            self.history = [
                h
                for h in self.history
                if h.started_at.timestamp() > cutoff
            ]

    def _calculate_delay(self, attempt: int, config: RetryConfig) -> float:
        """Calculate delay before next retry.

        Args:
            attempt: Attempt number (1-indexed)
            config: Retry configuration

        Returns:
            Delay in seconds
        """
        if attempt == 1:
            return 0.0

        base_delay = config.base_delay

        if config.strategy == RetryStrategy.EXPONENTIAL_BACKOFF:
            delay = base_delay * (config.multiplier ** (attempt - 2))
        elif config.strategy == RetryStrategy.LINEAR_BACKOFF:
            delay = base_delay * (attempt - 1)
        elif config.strategy == RetryStrategy.FIXED_DELAY:
            delay = base_delay
        else:  # IMMEDIATE
            delay = 0.0

        # Apply max delay cap
        delay = min(delay, config.max_delay)

        # Add jitter if configured
        if config.jitter and delay > 0:
            jitter_amount = delay * config.jitter_factor
            jitter = random.uniform(-jitter_amount, jitter_amount)
            delay = max(0, delay + jitter)

        return delay

    def _is_retryable_error(self, error_type: str, config: RetryConfig) -> bool:
        """Check if an error type is retryable.

        Args:
            error_type: Type name of the error
            config: Retry configuration

        Returns:
            True if the error should be retried
        """
        return error_type in config.retryable_exceptions


# Global retry manager instance
_retry_manager: Optional[RetryManager] = None


def get_retry_manager() -> RetryManager:
    """Get the global retry manager instance.

    Returns:
        Global RetryManager instance
    """
    global _retry_manager
    if _retry_manager is None:
        _retry_manager = RetryManager()
    return _retry_manager


def reset_retry_manager() -> None:
    """Reset the global retry manager instance."""
    global _retry_manager
    _retry_manager = None
