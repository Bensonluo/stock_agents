"""Timeout control for preventing long-running operations."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypeVar

T = TypeVar("T")

from app.utils.logging import get_logger

logger = get_logger(__name__)


class TimeoutResult(Enum):
    """Result of a timeout-protected operation."""

    COMPLETED = "completed"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass
class TimeoutStats:
    """Statistics for timeout operations."""

    name: str
    total_calls: int = 0
    completed_calls: int = 0
    timeout_calls: int = 0
    error_calls: int = 0
    total_execution_time: float = 0.0
    avg_execution_time: float = 0.0
    max_execution_time: float = 0.0
    recent_timeouts: List[Dict[str, Any]] = field(default_factory=list)

    def record_completion(
        self,
        execution_time: float,
        result: TimeoutResult,
    ) -> None:
        """Record a completed operation.

        Args:
            execution_time: Time taken for the operation
            result: Result of the operation
        """
        self.total_calls += 1
        self.total_execution_time += execution_time
        self.avg_execution_time = (
            self.total_execution_time / self.total_calls
            if self.total_calls > 0
            else 0.0
        )
        self.max_execution_time = max(self.max_execution_time, execution_time)

        if result == TimeoutResult.COMPLETED:
            self.completed_calls += 1
        elif result == TimeoutResult.TIMEOUT:
            self.timeout_calls += 1
            self.recent_timeouts.append({
                "timestamp": datetime.now().isoformat(),
                "execution_time": execution_time,
            })
            # Keep only recent 100 timeouts
            if len(self.recent_timeouts) > 100:
                self.recent_timeouts = self.recent_timeouts[-100:]
        else:
            self.error_calls += 1


class TimeLimiter:
    """Manages timeout control for operations.

    This class provides:
    - Per-operation timeout configuration
    - Timeout statistics tracking
    - Async and sync timeout protection

    Core learning: Understanding timeout patterns for fault tolerance.
    """

    def __init__(self, default_timeout: float = 300.0):
        """Initialize the time limiter.

        Args:
            default_timeout: Default timeout in seconds
        """
        self.default_timeout = default_timeout
        self.stats: Dict[str, TimeoutStats] = {}

    def get_stats(self, name: str) -> TimeoutStats:
        """Get or create statistics for a named operation.

        Args:
            name: Name of the operation

        Returns:
            TimeoutStats instance
        """
        if name not in self.stats:
            self.stats[name] = TimeoutStats(name=name)
        return self.stats[name]

    async def execute_with_timeout(
        self,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        timeout: Optional[float] = None,
        name: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:
        """Execute an async function with timeout protection.

        Args:
            func: Async function to execute
            *args: Positional arguments for the function
            timeout: Timeout in seconds (uses default if not provided)
            name: Optional name for tracking statistics
            **kwargs: Keyword arguments for the function

        Returns:
            Result from the function

        Raises:
            asyncio.TimeoutError: If operation times out
        """
        timeout = timeout or self.default_timeout
        operation_name = name or func.__name__
        stats = self.get_stats(operation_name)

        start_time = asyncio.get_event_loop().time()

        try:
            result = await asyncio.wait_for(func(*args, **kwargs), timeout=timeout)

            execution_time = asyncio.get_event_loop().time() - start_time
            stats.record_completion(execution_time, TimeoutResult.COMPLETED)

            logger.debug(
                f"Operation '{operation_name}' completed in {execution_time:.2f}s"
            )

            return result

        except asyncio.TimeoutError:
            execution_time = asyncio.get_event_loop().time() - start_time
            stats.record_completion(execution_time, TimeoutResult.TIMEOUT)

            logger.warning(
                f"Operation '{operation_name}' timed out after {execution_time:.2f}s "
                f"(limit: {timeout}s)"
            )

            raise

        except Exception as e:
            execution_time = asyncio.get_event_loop().time() - start_time
            stats.record_completion(execution_time, TimeoutResult.ERROR)

            logger.error(
                f"Operation '{operation_name}' failed after {execution_time:.2f}s: {e}"
            )

            raise

    def execute_with_timeout_sync(
        self,
        func: Callable[..., T],
        *args: Any,
        timeout: Optional[float] = None,
        name: Optional[str] = None,
        **kwargs: Any,
    ) -> T:
        """Execute a synchronous function with timeout protection.

        Args:
            func: Function to execute
            *args: Positional arguments for the function
            timeout: Timeout in seconds (uses default if not provided)
            name: Optional name for tracking statistics
            **kwargs: Keyword arguments for the function

        Returns:
            Result from the function

        Raises:
            TimeoutError: If operation times out
        """
        import signal
        from threading import Thread

        timeout = timeout or self.default_timeout
        operation_name = name or func.__name__
        stats = self.get_stats(operation_name)

        result = None
        error = None
        execution_time = 0.0

        def target():
            nonlocal result, error, execution_time
            import time
            start = time.time()
            try:
                result = func(*args, **kwargs)
            except Exception as e:
                error = e
            execution_time = time.time() - start

        thread = Thread(target=target)
        thread.daemon = True
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            # Thread is still running, so it timed out
            stats.record_completion(timeout, TimeoutResult.TIMEOUT)
            logger.warning(
                f"Operation '{operation_name}' timed out after {timeout}s"
            )
            raise TimeoutError(f"Operation '{operation_name}' timed out after {timeout}s")

        if error is not None:
            stats.record_completion(execution_time, TimeoutResult.ERROR)
            logger.error(
                f"Operation '{operation_name}' failed after {execution_time:.2f}s: {error}"
            )
            raise error

        stats.record_completion(execution_time, TimeoutResult.COMPLETED)
        logger.debug(
            f"Operation '{operation_name}' completed in {execution_time:.2f}s"
        )

        return result

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for all tracked operations.

        Returns:
            Dictionary mapping operation names to statistics
        """
        return {
            name: {
                "total_calls": s.total_calls,
                "completed_calls": s.completed_calls,
                "timeout_calls": s.timeout_calls,
                "error_calls": s.error_calls,
                "avg_execution_time": s.avg_execution_time,
                "max_execution_time": s.max_execution_time,
                "timeout_rate": (
                    s.timeout_calls / s.total_calls if s.total_calls > 0 else 0.0
                ),
            }
            for name, s in self.stats.items()
        }

    def reset_stats(self, name: Optional[str] = None) -> None:
        """Reset statistics.

        Args:
            name: Optional name of specific operation.
                If None, resets all statistics.
        """
        if name:
            self.stats.pop(name, None)
        else:
            self.stats.clear()


# Global time limiter instance
_time_limiter: Optional[TimeLimiter] = None


def get_time_limiter() -> TimeLimiter:
    """Get the global time limiter instance.

    Returns:
        Global TimeLimiter instance
    """
    global _time_limiter
    if _time_limiter is None:
        from app.config import settings

        _time_limiter = TimeLimiter(default_timeout=settings.timeout_per_agent)
    return _time_limiter


def reset_time_limiter() -> None:
    """Reset the global time limiter instance."""
    global _time_limiter
    _time_limiter = None
