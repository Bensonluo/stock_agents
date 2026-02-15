"""Metrics definitions for agent monitoring."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import statistics


class AgentStatus(Enum):
    """Agent status enumeration."""

    IDLE = "idle"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    RETRYING = "retrying"


class AlertSeverity(Enum):
    """Alert severity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class AgentMetrics:
    """Agent metrics data class.

    This class tracks comprehensive metrics for each agent:
    - Execution counts (total, successful, failed, timeout)
    - Time metrics (avg, min, max, p95, p99)
    - Error statistics by type
    - Health score calculation

    Core learning: Understanding what metrics are important for
    monitoring distributed systems.
    """

    agent_name: str

    # Execution counts
    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    timeout_executions: int = 0

    # Time metrics
    total_execution_time: float = 0.0
    avg_execution_time: float = 0.0
    min_execution_time: float = float("inf")
    max_execution_time: float = 0.0
    p95_execution_time: float = 0.0
    p99_execution_time: float = 0.0

    # Recent execution time list (for percentile calculation)
    recent_execution_times: List[float] = field(default_factory=list)

    # Error statistics
    errors_by_type: Dict[str, int] = field(default_factory=dict)
    last_error: Optional[Dict] = None
    last_failure_time: Optional[datetime] = None

    # Health
    success_rate: float = 1.0
    health_score: float = 100.0

    # Current status
    current_status: AgentStatus = AgentStatus.IDLE

    def calculate_success_rate(self) -> float:
        """Calculate success rate.

        Returns:
            Success rate as a float between 0 and 1
        """
        if self.total_executions == 0:
            return 1.0
        return self.successful_executions / self.total_executions

    def calculate_health_score(self) -> float:
        """Calculate health score (0-100).

        The health score combines multiple factors:
        - Success rate (60% weight)
        - Time stability (20% weight)
        - Recent failure penalty (20% weight)

        Returns:
            Health score from 0 to 100
        """
        # Success rate score (60% weight)
        success_rate_score = self.calculate_success_rate() * 60

        # Time stability score (20% weight)
        # Based on coefficient of variation
        if len(self.recent_execution_times) > 1:
            mean = statistics.mean(self.recent_execution_times)
            if mean > 0:
                std_dev = statistics.stdev(self.recent_execution_times)
                cv = std_dev / mean
                stability_score = max(0, 20 - cv * 100)
            else:
                stability_score = 20
        else:
            stability_score = 20

        # Recent failure penalty (20% weight)
        recent_failure_penalty = 0.0
        if self.last_failure_time:
            time_since_failure = (datetime.now() - self.last_failure_time).total_seconds()
            # Decay penalty over 1 hour
            recent_failure_penalty = max(0, 20 * (1 - time_since_failure / 3600))

        health_score = success_rate_score + stability_score - recent_failure_penalty
        return max(0, min(100, health_score))

    def update_percentiles(self) -> None:
        """Update P95 and P99 execution times.

        Keeps only the most recent 100 execution times for calculation.
        """
        # Keep only recent values
        if len(self.recent_execution_times) > 100:
            self.recent_execution_times = self.recent_execution_times[-100:]

        if self.recent_execution_times:
            sorted_times = sorted(self.recent_execution_times)
            n = len(sorted_times)
            self.p95_execution_time = sorted_times[int(n * 0.95)] if n > 0 else 0.0
            self.p99_execution_time = sorted_times[int(n * 0.99)] if n > 0 else 0.0

    def record_execution(
        self,
        success: bool,
        execution_time: float,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        timeout: bool = False,
    ) -> None:
        """Record an agent execution.

        Args:
            success: Whether the execution was successful
            execution_time: Time taken for execution in seconds
            error_type: Type of error if failed
            error_message: Error message if failed
            timeout: Whether the execution timed out
        """
        # Update counts
        self.total_executions += 1
        if success:
            self.successful_executions += 1
        elif timeout:
            self.timeout_executions += 1
        else:
            self.failed_executions += 1

        # Update time metrics
        self.total_execution_time += execution_time
        self.avg_execution_time = self.total_execution_time / self.total_executions
        self.min_execution_time = min(self.min_execution_time, execution_time)
        self.max_execution_time = max(self.max_execution_time, execution_time)

        # Record execution time for percentile calculation
        self.recent_execution_times.append(execution_time)
        self.update_percentiles()

        # Record error if failed
        if not success and error_type:
            if error_type not in self.errors_by_type:
                self.errors_by_type[error_type] = 0
            self.errors_by_type[error_type] += 1

            self.last_error = {
                "type": error_type,
                "message": error_message,
                "timestamp": datetime.now(),
            }
            self.last_failure_time = datetime.now()

        # Update health metrics
        self.success_rate = self.calculate_success_rate()
        self.health_score = self.calculate_health_score()

    def get_summary(self) -> Dict[str, any]:
        """Get a summary of metrics.

        Returns:
            Dictionary containing key metrics
        """
        return {
            "agent_name": self.agent_name,
            "status": self.current_status.value,
            "total_executions": self.total_executions,
            "successful_executions": self.successful_executions,
            "failed_executions": self.failed_executions,
            "timeout_executions": self.timeout_executions,
            "success_rate": self.success_rate,
            "health_score": self.health_score,
            "avg_execution_time": self.avg_execution_time,
            "min_execution_time": (
                self.min_execution_time if self.min_execution_time != float("inf") else 0.0
            ),
            "max_execution_time": self.max_execution_time,
            "p95_execution_time": self.p95_execution_time,
            "p99_execution_time": self.p99_execution_time,
            "errors_by_type": self.errors_by_type,
            "last_error": self.last_error,
            "last_failure_time": self.last_failure_time.isoformat()
            if self.last_failure_time
            else None,
        }


@dataclass
class Alert:
    """Alert data class."""

    alert_id: str
    severity: AlertSeverity
    type: str
    agent: str
    message: str
    timestamp: datetime
    metadata: Dict[str, any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, any]:
        """Convert alert to dictionary."""
        return {
            "alert_id": self.alert_id,
            "severity": self.severity.value,
            "type": self.type,
            "agent": self.agent,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class EventLog:
    """Event log entry for tracking agent lifecycle events."""

    event_type: str
    agent: str
    timestamp: datetime
    data: Dict[str, any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, any]:
        """Convert event log to dictionary."""
        return {
            "event_type": self.event_type,
            "agent": self.agent,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
        }


@dataclass
class AgentExecutionLog:
    """智能体执行日志 - 记录详细执行步骤

    This class tracks detailed execution steps for agents:
    - Step-by-step logging with log levels
    - Thread-based correlation for workflow tracking
    - Optional timing data for performance analysis
    """

    log_id: str
    thread_id: str
    agent_name: str
    step: int
    level: str  # 'info', 'warning', 'error', 'debug'
    message: str
    timestamp: datetime
    data: Dict[str, Any] = field(default_factory=dict)
    duration_ms: Optional[int] = None

    def to_dict(self) -> Dict[str, any]:
        """Convert log to dictionary."""
        return {
            "log_id": self.log_id,
            "thread_id": self.thread_id,
            "agent_name": self.agent_name,
            "step": self.step,
            "level": self.level,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
            "duration_ms": self.duration_ms,
        }
