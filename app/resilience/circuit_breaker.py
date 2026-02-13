"""Circuit breaker pattern implementation for preventing cascading failures."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from app.utils.logging import get_logger

logger = get_logger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Circuit is open, blocking requests
    HALF_OPEN = "half_open"  # Testing if service has recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior."""

    failure_threshold: int = 5  # Number of failures before opening
    success_threshold: int = 2  # Number of successes to close from half-open
    timeout: int = 60  # Seconds to wait before trying half-open
    rolling_window: int = 100  # Number of recent calls to track
    min_calls: int = 5  # Minimum calls before calculating failure rate


@dataclass
class CallResult:
    """Result of a single call."""

    success: bool
    timestamp: datetime
    latency: float = 0.0
    error: Optional[str] = None


@dataclass
class CircuitBreakerStats:
    """Statistics for a circuit breaker."""

    name: str
    state: CircuitState = CircuitState.CLOSED
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    last_failure_time: Optional[datetime] = None
    last_state_change: Optional[datetime] = None
    recent_results: List[CallResult] = field(default_factory=list)
    opened_count: int = 0  # Number of times circuit has opened

    def failure_rate(self) -> float:
        """Calculate current failure rate."""
        if self.total_calls == 0:
            return 0.0
        return self.failed_calls / self.total_calls

    def add_result(self, result: CallResult, max_window: int) -> None:
        """Add a call result to the stats."""
        self.recent_results.append(result)

        # Keep only recent results
        if len(self.recent_results) > max_window:
            self.recent_results = self.recent_results[-max_window:]

        self.total_calls += 1
        if result.success:
            self.successful_calls += 1
        else:
            self.failed_calls += 1
            self.last_failure_time = result.timestamp


class CircuitBreaker:
    """Circuit breaker for preventing cascading failures.

    The circuit breaker pattern works like a real electrical circuit breaker:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Too many failures, requests are blocked
    - HALF_OPEN: Testing if the service has recovered

    Core learning: Understanding fault tolerance patterns for distributed systems.
    """

    def __init__(self, name: str, config: Optional[CircuitBreakerConfig] = None):
        """Initialize the circuit breaker.

        Args:
            name: Unique name for this circuit breaker
            config: Circuit breaker configuration
        """
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.stats = CircuitBreakerStats(name=name)
        self._lock = None  # Could use threading.Lock for thread safety

    def is_open(self) -> bool:
        """Check if the circuit is currently open.

        Returns:
            True if circuit is open and blocking requests
        """
        # Check if we should transition from OPEN to HALF_OPEN
        if (
            self.stats.state == CircuitState.OPEN
            and self.stats.last_state_change
            and (datetime.now() - self.stats.last_state_change).total_seconds()
            > self.config.timeout
        ):
            self._transition_to(CircuitState.HALF_OPEN)
            logger.info(f"Circuit breaker '{self.name}' transitioned to HALF_OPEN")

        return self.stats.state == CircuitState.OPEN

    def allow_request(self) -> bool:
        """Check if a request should be allowed.

        Returns:
            True if request should proceed, False if blocked
        """
        return not self.is_open()

    def record_success(self, latency: float = 0.0) -> None:
        """Record a successful call.

        Args:
            latency: Call latency in seconds
        """
        result = CallResult(
            success=True,
            timestamp=datetime.now(),
            latency=latency,
        )

        self.stats.add_result(result, self.config.rolling_window)

        # If in HALF_OPEN, successful calls may close the circuit
        if self.stats.state == CircuitState.HALF_OPEN:
            # Count recent consecutive successes
            recent = self.stats.recent_results[-self.config.success_threshold :]
            if all(r.success for r in recent):
                self._transition_to(CircuitState.CLOSED)
                logger.info(
                    f"Circuit breaker '{self.name}' closed after "
                    f"{self.config.success_threshold} consecutive successes"
                )

        logger.debug(f"Circuit breaker '{self.name}' recorded success")

    def record_failure(self, error: Optional[str] = None) -> None:
        """Record a failed call.

        Args:
            error: Optional error message
        """
        result = CallResult(
            success=False,
            timestamp=datetime.now(),
            error=error,
        )

        self.stats.add_result(result, self.config.rolling_window)

        # Check if we should open the circuit
        should_open = False

        if self.stats.state == CircuitState.HALF_OPEN:
            # Any failure in HALF_OPEN opens the circuit
            should_open = True
        elif self.stats.state == CircuitState.CLOSED:
            # Check if we've exceeded the failure threshold
            recent_failures = sum(
                1 for r in self.stats.recent_results[-self.config.failure_threshold :]
                if not r.success
            )
            if recent_failures >= self.config.failure_threshold:
                should_open = True

        if should_open:
            self._transition_to(CircuitState.OPEN)
            self.stats.opened_count += 1
            logger.warning(
                f"Circuit breaker '{self.name}' opened after {self.config.failure_threshold} failures"
            )

        logger.debug(f"Circuit breaker '{self.name}' recorded failure")

    def get_state(self) -> CircuitState:
        """Get the current circuit state.

        Returns:
            Current circuit state
        """
        # Update state based on timeout
        self.is_open()  # This triggers state transition if needed
        return self.stats.state

    def get_stats(self) -> Dict[str, Any]:
        """Get circuit breaker statistics.

        Returns:
            Dictionary containing statistics
        """
        return {
            "name": self.name,
            "state": self.stats.state.value,
            "total_calls": self.stats.total_calls,
            "successful_calls": self.stats.successful_calls,
            "failed_calls": self.stats.failed_calls,
            "failure_rate": self.stats.failure_rate(),
            "last_failure_time": (
                self.stats.last_failure_time.isoformat()
                if self.stats.last_failure_time
                else None
            ),
            "last_state_change": (
                self.stats.last_state_change.isoformat()
                if self.stats.last_state_change
                else None
            ),
            "opened_count": self.stats.opened_count,
            "config": {
                "failure_threshold": self.config.failure_threshold,
                "success_threshold": self.config.success_threshold,
                "timeout": self.config.timeout,
            },
        }

    def reset(self) -> None:
        """Reset the circuit breaker to CLOSED state."""
        self._transition_to(CircuitState.CLOSED)
        self.stats.opened_count = 0
        self.stats.recent_results.clear()
        logger.info(f"Circuit breaker '{self.name}' reset to CLOSED state")

    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state.

        Args:
            new_state: New state to transition to
        """
        old_state = self.stats.state
        self.stats.state = new_state
        self.stats.last_state_change = datetime.now()

        logger.debug(
            f"Circuit breaker '{self.name}' transitioned from {old_state.value} to {new_state.value}"
        )


class CircuitBreakerRegistry:
    """Registry for managing multiple circuit breakers.

    This provides a centralized way to manage circuit breakers for
    different agents or services.
    """

    def __init__(self, default_config: Optional[CircuitBreakerConfig] = None):
        """Initialize the registry.

        Args:
            default_config: Default configuration for new circuit breakers
        """
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.default_config = default_config or CircuitBreakerConfig()

    def get(self, name: str) -> CircuitBreaker:
        """Get or create a circuit breaker by name.

        Args:
            name: Name of the circuit breaker

        Returns:
            CircuitBreaker instance
        """
        if name not in self.circuit_breakers:
            self.circuit_breakers[name] = CircuitBreaker(
                name=name, config=self.default_config
            )
        return self.circuit_breakers[name]

    def is_open(self, name: str) -> bool:
        """Check if a circuit breaker is open.

        Args:
            name: Name of the circuit breaker

        Returns:
            True if the circuit is open
        """
        return self.get(name).is_open()

    def allow_request(self, name: str) -> bool:
        """Check if a request should be allowed.

        Args:
            name: Name of the circuit breaker

        Returns:
            True if request should proceed
        """
        return self.get(name).allow_request()

    def record_success(self, name: str, latency: float = 0.0) -> None:
        """Record a successful call.

        Args:
            name: Name of the circuit breaker
            latency: Call latency in seconds
        """
        self.get(name).record_success(latency)

    def record_failure(self, name: str, error: Optional[str] = None) -> None:
        """Record a failed call.

        Args:
            name: Name of the circuit breaker
            error: Optional error message
        """
        self.get(name).record_failure(error)

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for all circuit breakers.

        Returns:
            Dictionary mapping names to statistics
        """
        return {
            name: cb.get_stats() for name, cb in self.circuit_breakers.items()
        }

    def get_open_circuits(self) -> List[str]:
        """Get list of circuit breakers that are currently open.

        Returns:
            List of circuit breaker names
        """
        return [
            name
            for name, cb in self.circuit_breakers.items()
            if cb.get_state() == CircuitState.OPEN
        ]

    def reset(self, name: Optional[str] = None) -> None:
        """Reset one or all circuit breakers.

        Args:
            name: Optional name of specific circuit breaker.
                If None, resets all circuit breakers.
        """
        if name:
            if name in self.circuit_breakers:
                self.circuit_breakers[name].reset()
        else:
            for cb in self.circuit_breakers.values():
                cb.reset()

    def remove(self, name: str) -> None:
        """Remove a circuit breaker from the registry.

        Args:
            name: Name of the circuit breaker to remove
        """
        self.circuit_breakers.pop(name, None)


# Global circuit breaker registry
_circuit_breaker_registry: Optional[CircuitBreakerRegistry] = None


def get_circuit_breaker_registry() -> CircuitBreakerRegistry:
    """Get the global circuit breaker registry.

    Returns:
        Global CircuitBreakerRegistry instance
    """
    global _circuit_breaker_registry
    if _circuit_breaker_registry is None:
        from app.config import settings

        config = CircuitBreakerConfig(
            failure_threshold=settings.circuit_breaker_failure_threshold,
            timeout=settings.circuit_breaker_recovery_timeout,
        )
        _circuit_breaker_registry = CircuitBreakerRegistry(default_config=config)
    return _circuit_breaker_registry


def reset_circuit_breaker_registry() -> None:
    """Reset the global circuit breaker registry."""
    global _circuit_breaker_registry
    _circuit_breaker_registry = None
