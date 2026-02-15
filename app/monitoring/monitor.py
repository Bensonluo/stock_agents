"""Agent monitoring system for tracking execution metrics."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from app.monitoring.metrics import (
    AgentExecutionLog,
    Alert,
    AlertSeverity,
    AgentMetrics,
    AgentStatus,
    EventLog,
)
from app.utils.logging import get_logger

if TYPE_CHECKING:
    from app.orchestration.state import AgentState

logger = get_logger(__name__)


class AgentMonitor:
    """Agent monitor for tracking execution metrics and generating alerts.

    This class provides:
    - Real-time metric collection (success rate, latency, health score)
    - Event tracking for agent lifecycle
    - Alert generation for anomalous conditions
    - System-wide overview and individual agent health

    Core learning: Building enterprise-grade monitoring systems.
    """

    def __init__(self, alert_thresholds: Optional[Dict] = None):
        """Initialize the agent monitor.

        Args:
            alert_thresholds: Optional custom alert thresholds
        """
        self.metrics: Dict[str, AgentMetrics] = {}
        self.alert_thresholds = alert_thresholds or {
            "success_rate": 0.95,
            "avg_execution_time": 30.0,
            "health_score": 70.0,
            "error_count": 10,
        }
        self.alert_handlers: List[Callable] = []
        self.event_log: List[EventLog] = []
        self.alerts: List[Alert] = []
        self.execution_logs: Dict[str, List[AgentExecutionLog]] = {}

        self._lock = None  # Could use threading.Lock for thread safety
        self.broadcast_manager = None  # Optional ConnectionManager for WebSocket broadcasts

    def register_agent(self, agent_name: str) -> None:
        """Register an agent for monitoring.

        Args:
            agent_name: Name of the agent to register
        """
        if agent_name not in self.metrics:
            self.metrics[agent_name] = AgentMetrics(agent_name=agent_name)
            logger.debug(f"Registered agent for monitoring: {agent_name}")

    def on_agent_start(
        self,
        agent_name: str,
        state: "AgentState",
        metadata: Optional[Dict] = None,
    ) -> None:
        """Called when an agent starts execution.

        Args:
            agent_name: Name of the agent
            state: Current agent state
            metadata: Optional additional metadata
        """
        self.register_agent(agent_name)

        metrics = self.metrics[agent_name]
        metrics.current_status = AgentStatus.RUNNING

        event = EventLog(
            event_type="agent_start",
            agent=agent_name,
            timestamp=datetime.now(),
            data={
                "thread_id": state.get("thread_id"),
                "symbols": state.get("symbols", []),
                "query": state.get("query", ""),
                "step": state.get("current_step", 0),
                "metadata": metadata or {},
            },
        )

        self._log_event(event)
        logger.debug(f"Agent started: {agent_name}")

    def on_agent_success(
        self,
        agent_name: str,
        execution_time: float,
        result: Optional[Dict] = None,
        metadata: Optional[Dict] = None,
        thread_id: Optional[str] = None,
    ) -> None:
        """Called when an agent completes successfully.

        Args:
            agent_name: Name of the agent
            execution_time: Time taken for execution in seconds
            result: Optional result data
            metadata: Optional additional metadata
            thread_id: Optional workflow thread ID
        """
        self.register_agent(agent_name)

        metrics = self.metrics[agent_name]
        metrics.current_status = AgentStatus.SUCCESS
        metrics.record_execution(
            success=True,
            execution_time=execution_time,
        )

        event = EventLog(
            event_type="agent_success",
            agent=agent_name,
            timestamp=datetime.now(),
            data={
                "thread_id": thread_id,
                "execution_time": execution_time,
                "result_summary": self._summarize_result(result) if result else {},
                "metadata": metadata or {},
            },
        )

        self._log_event(event)
        logger.debug(
            f"Agent succeeded: {agent_name} in {execution_time:.2f}s, "
            f"health: {metrics.health_score:.1f}"
        )

    def on_agent_failure(
        self,
        agent_name: str,
        error: str,
        execution_time: float,
        error_type: str = "UnknownError",
        metadata: Optional[Dict] = None,
        thread_id: Optional[str] = None,
    ) -> None:
        """Called when an agent fails.

        Args:
            agent_name: Name of the agent
            error: Error message
            execution_time: Time taken before failure
            error_type: Type of error
            metadata: Optional additional metadata
            thread_id: Optional workflow thread ID
        """
        self.register_agent(agent_name)

        metrics = self.metrics[agent_name]
        metrics.current_status = AgentStatus.FAILED
        metrics.record_execution(
            success=False,
            execution_time=execution_time,
            error_type=error_type,
            error_message=error,
        )

        event = EventLog(
            event_type="agent_failure",
            agent=agent_name,
            timestamp=datetime.now(),
            data={
                "thread_id": thread_id,
                "error": error,
                "error_type": error_type,
                "execution_time": execution_time,
                "metadata": metadata or {},
            },
        )

        self._log_event(event)

        # Check and trigger alerts
        self._check_and_trigger_alerts(agent_name)

        logger.warning(
            f"Agent failed: {agent_name} - {error_type}: {error}, "
            f"health: {metrics.health_score:.1f}"
        )

    def on_agent_timeout(
        self,
        agent_name: str,
        timeout_limit: float,
        metadata: Optional[Dict] = None,
    ) -> None:
        """Called when an agent times out.

        Args:
            agent_name: Name of the agent
            timeout_limit: Timeout threshold in seconds
            metadata: Optional additional metadata
        """
        self.register_agent(agent_name)

        metrics = self.metrics[agent_name]
        metrics.current_status = AgentStatus.TIMEOUT
        metrics.record_execution(
            success=False,
            execution_time=timeout_limit,
            error_type="TimeoutError",
            error_message=f"Agent timeout after {timeout_limit}s",
            timeout=True,
        )

        event = EventLog(
            event_type="agent_timeout",
            agent=agent_name,
            timestamp=datetime.now(),
            data={
                "timeout_limit": timeout_limit,
                "metadata": metadata or {},
            },
        )

        self._log_event(event)

        # Trigger alert for timeout
        alert = Alert(
            alert_id=str(uuid.uuid4()),
            severity=AlertSeverity.HIGH,
            type="AGENT_TIMEOUT",
            agent=agent_name,
            message=f"Agent {agent_name} timed out after {timeout_limit}s",
            timestamp=datetime.now(),
        )

        self._trigger_alert(alert)
        logger.error(f"Agent timeout: {agent_name} after {timeout_limit}s")

    def on_agent_retry(
        self,
        agent_name: str,
        retry_count: int,
        max_retries: int,
        last_error: Optional[str] = None,
    ) -> None:
        """Called when an agent is being retried.

        Args:
            agent_name: Name of the agent
            retry_count: Current retry attempt number
            max_retries: Maximum retry attempts allowed
            last_error: Optional last error message
        """
        self.register_agent(agent_name)

        metrics = self.metrics[agent_name]
        metrics.current_status = AgentStatus.RETRYING

        event = EventLog(
            event_type="agent_retry",
            agent=agent_name,
            timestamp=datetime.now(),
            data={
                "retry_count": retry_count,
                "max_retries": max_retries,
                "last_error": last_error,
            },
        )

        self._log_event(event)
        logger.info(f"Agent retry: {agent_name} (attempt {retry_count}/{max_retries})")

    def get_agent_health(self, agent_name: str) -> Dict:
        """Get the health status of a specific agent.

        Args:
            agent_name: Name of the agent

        Returns:
            Dictionary containing health information
        """
        metrics = self.metrics.get(agent_name)
        if not metrics:
            return {"status": "unknown", "agent": agent_name}

        summary = metrics.get_summary()
        summary["recommendations"] = self._generate_health_recommendations(metrics)

        return summary

    def get_system_overview(self) -> Dict:
        """Get an overview of the entire system.

        Returns:
            Dictionary containing system-wide metrics
        """
        total_executions = sum(m.total_executions for m in self.metrics.values())
        total_successful = sum(m.successful_executions for m in self.metrics.values())
        total_failed = sum(m.failed_executions for m in self.metrics.values())
        total_timeout = sum(m.timeout_executions for m in self.metrics.values())

        # Calculate overall success rate
        overall_success_rate = (
            total_successful / total_executions if total_executions > 0 else 1.0
        )

        # Calculate average health score
        avg_health_score = (
            sum(m.health_score for m in self.metrics.values()) / len(self.metrics)
            if self.metrics
            else 100.0
        )

        # Get unhealthy agents
        unhealthy_agents = [
            name
            for name, metrics in self.metrics.items()
            if metrics.health_score < self.alert_thresholds["health_score"]
        ]

        return {
            "timestamp": datetime.now().isoformat(),
            "total_agents": len(self.metrics),
            "total_executions": total_executions,
            "total_successful": total_successful,
            "total_failed": total_failed,
            "total_timeout": total_timeout,
            "overall_success_rate": overall_success_rate,
            "avg_health_score": avg_health_score,
            "agents_health": {
                name: metrics.health_score for name, metrics in self.metrics.items()
            },
            "unhealthy_agents": unhealthy_agents,
            "recent_events": [e.to_dict() for e in self.event_log[-50:]],
            "active_alerts": [a.to_dict() for a in self.alerts if self._is_alert_active(a)],
        }

    def get_metrics(self, agent_name: Optional[str] = None) -> Dict:
        """Get metrics for a specific agent or all agents.

        Args:
            agent_name: Optional agent name. If None, returns all metrics.

        Returns:
            Dictionary containing requested metrics
        """
        if agent_name:
            return self.get_agent_health(agent_name)

        return {
            name: metrics.get_summary() for name, metrics in self.metrics.items()
        }

    def get_events(
        self,
        agent_name: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """Get event log entries.

        Args:
            agent_name: Optional agent name filter
            event_type: Optional event type filter
            limit: Maximum number of events to return

        Returns:
            List of event log entries as dictionaries
        """
        events = self.event_log

        # Apply filters
        if agent_name:
            events = [e for e in events if e.agent == agent_name]
        if event_type:
            events = [e for e in events if e.event_type == event_type]

        # Get most recent
        events = events[-limit:]

        return [e.to_dict() for e in reversed(events)]

    def get_alerts(
        self,
        severity: Optional[AlertSeverity] = None,
        agent_name: Optional[str] = None,
        active_only: bool = True,
        limit: int = 50,
    ) -> List[Dict]:
        """Get alerts.

        Args:
            severity: Optional severity filter
            agent_name: Optional agent name filter
            active_only: Whether to return only active alerts
            limit: Maximum number of alerts to return

        Returns:
            List of alerts as dictionaries
        """
        alerts = self.alerts

        # Apply filters
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        if agent_name:
            alerts = [a for a in alerts if a.agent == agent_name]
        if active_only:
            alerts = [a for a in alerts if self._is_alert_active(a)]

        # Get most recent
        alerts = alerts[-limit:]

        return [a.to_dict() for a in reversed(alerts)]

    def add_alert_handler(self, handler: Callable[[Alert], None]) -> None:
        """Add an alert handler callback.

        Args:
            handler: Function to call when an alert is triggered
        """
        self.alert_handlers.append(handler)
        logger.debug(f"Added alert handler: {handler.__name__}")

    def reset_metrics(self, agent_name: Optional[str] = None) -> None:
        """Reset metrics for a specific agent or all agents.

        Args:
            agent_name: Optional agent name. If None, resets all.
        """
        if agent_name:
            if agent_name in self.metrics:
                self.metrics[agent_name] = AgentMetrics(agent_name=agent_name)
                logger.info(f"Reset metrics for agent: {agent_name}")
        else:
            self.metrics.clear()
            logger.info("Reset all metrics")

    def reset_events(self) -> None:
        """Clear the event log."""
        self.event_log.clear()
        logger.info("Cleared event log")

    def reset_alerts(self) -> None:
        """Clear the alert history."""
        self.alerts.clear()
        logger.info("Cleared alerts")

    # ========== Execution Logging Methods ==========

    def log_agent_step(
        self,
        thread_id: str,
        agent_name: str,
        step: int,
        level: str,
        message: str,
        data: Optional[Dict] = None,
        duration_ms: Optional[int] = None,
    ) -> None:
        """Record an agent execution step.

        Args:
            thread_id: Thread ID for correlating logs across a workflow
            agent_name: Name of the agent
            step: Step number in the execution sequence
            level: Log level ('info', 'warning', 'error', 'debug')
            message: Log message
            data: Optional additional data
            duration_ms: Optional duration in milliseconds
        """
        log_entry = AgentExecutionLog(
            log_id=str(uuid.uuid4()),
            thread_id=thread_id,
            agent_name=agent_name,
            step=step,
            level=level,
            message=message,
            timestamp=datetime.now(),
            data=data or {},
            duration_ms=duration_ms,
        )

        # Initialize agent log list if not exists
        if agent_name not in self.execution_logs:
            self.execution_logs[agent_name] = []

        self.execution_logs[agent_name].append(log_entry)

        # Limit log size per agent
        if len(self.execution_logs[agent_name]) > 5000:
            self.execution_logs[agent_name] = self.execution_logs[agent_name][-5000:]

        # Log based on level
        log_msg = f"[{thread_id}] {agent_name} step={step}: {message}"
        if level == "error":
            logger.error(log_msg)
        elif level == "warning":
            logger.warning(log_msg)
        elif level == "debug":
            logger.debug(log_msg)
        else:
            logger.info(log_msg)

    def get_agent_logs(
        self,
        agent_name: str,
        thread_id: Optional[str] = None,
        level: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """Get logs for a specific agent.

        Args:
            agent_name: Name of the agent
            thread_id: Optional thread ID filter
            level: Optional log level filter
            limit: Maximum number of logs to return

        Returns:
            List of log entries as dictionaries
        """
        logs = self.execution_logs.get(agent_name, [])

        # Apply filters
        if thread_id:
            logs = [log for log in logs if log.thread_id == thread_id]
        if level:
            logs = [log for log in logs if log.level == level]

        # Get most recent logs
        logs = logs[-limit:]

        return [log.to_dict() for log in reversed(logs)]

    def get_workflow_logs(
        self,
        thread_id: str,
        limit: int = 500,
    ) -> List[Dict]:
        """Get all logs for a workflow thread.

        Args:
            thread_id: Thread ID to filter by
            limit: Maximum number of logs to return

        Returns:
            List of log entries as dictionaries, sorted by timestamp
        """
        all_logs = []

        # Collect logs from all agents for this thread
        for agent_logs in self.execution_logs.values():
            for log in agent_logs:
                if log.thread_id == thread_id:
                    all_logs.append(log)

        # Sort by timestamp
        all_logs.sort(key=lambda x: x.timestamp)

        # Apply limit
        all_logs = all_logs[-limit:]

        return [log.to_dict() for log in all_logs]

    def clear_agent_logs(self, agent_name: Optional[str] = None) -> None:
        """Clear execution logs.

        Args:
            agent_name: Optional agent name. If None, clears all logs.
        """
        if agent_name:
            if agent_name in self.execution_logs:
                del self.execution_logs[agent_name]
                logger.info(f"Cleared execution logs for agent: {agent_name}")
        else:
            self.execution_logs.clear()
            logger.info("Cleared all execution logs")

    # ========== Private Methods ==========

    def _log_event(self, event: EventLog) -> None:
        """Add an event to the log.

        Args:
            event: Event to log
        """
        self.event_log.append(event)

        # Limit log size
        if len(self.event_log) > 10000:
            self.event_log = self.event_log[-10000:]

    def _check_and_trigger_alerts(self, agent_name: str) -> None:
        """Check metrics and trigger alerts if thresholds are exceeded.

        Args:
            agent_name: Name of the agent to check
        """
        metrics = self.metrics.get(agent_name)
        if not metrics:
            return

        alerts = []

        # Success rate alert
        if metrics.success_rate < self.alert_thresholds["success_rate"]:
            alerts.append(
                Alert(
                    alert_id=str(uuid.uuid4()),
                    severity=AlertSeverity.HIGH,
                    type="LOW_SUCCESS_RATE",
                    agent=agent_name,
                    message=f"Agent {agent_name} success rate dropped to {metrics.success_rate:.2%}",
                    timestamp=datetime.now(),
                    metadata={
                        "current_value": metrics.success_rate,
                        "threshold": self.alert_thresholds["success_rate"],
                    },
                )
            )

        # Health score alert
        if metrics.health_score < self.alert_thresholds["health_score"]:
            alerts.append(
                Alert(
                    alert_id=str(uuid.uuid4()),
                    severity=AlertSeverity.MEDIUM,
                    type="LOW_HEALTH_SCORE",
                    agent=agent_name,
                    message=f"Agent {agent_name} health score is {metrics.health_score:.1f}/100",
                    timestamp=datetime.now(),
                    metadata={
                        "current_value": metrics.health_score,
                        "threshold": self.alert_thresholds["health_score"],
                    },
                )
            )

        # Execution time alert
        if (
            metrics.avg_execution_time > self.alert_thresholds["avg_execution_time"]
            and metrics.total_executions > 5
        ):
            alerts.append(
                Alert(
                    alert_id=str(uuid.uuid4()),
                    severity=AlertSeverity.MEDIUM,
                    type="HIGH_EXECUTION_TIME",
                    agent=agent_name,
                    message=f"Agent {agent_name} avg execution time is {metrics.avg_execution_time:.2f}s",
                    timestamp=datetime.now(),
                    metadata={
                        "current_value": metrics.avg_execution_time,
                        "threshold": self.alert_thresholds["avg_execution_time"],
                    },
                )
            )

        # Trigger all alerts
        for alert in alerts:
            self._trigger_alert(alert)

    def _trigger_alert(self, alert: Alert) -> None:
        """Trigger an alert by calling all registered handlers.

        Args:
            alert: Alert to trigger
        """
        self.alerts.append(alert)

        for handler in self.alert_handlers:
            try:
                handler(alert)
            except Exception as e:
                logger.error(f"Alert handler failed: {e}")

    def _is_alert_active(self, alert: Alert) -> bool:
        """Check if an alert is still active.

        An alert is considered active if it occurred within the last 5 minutes.

        Args:
            alert: Alert to check

        Returns:
            True if alert is active
        """
        time_since_alert = (datetime.now() - alert.timestamp).total_seconds()
        return time_since_alert < 300  # 5 minutes

    def _generate_health_recommendations(self, metrics: AgentMetrics) -> List[str]:
        """Generate health recommendations based on metrics.

        Args:
            metrics: Agent metrics to analyze

        Returns:
            List of recommendation strings
        """
        recommendations = []

        if metrics.success_rate < 0.9:
            recommendations.append("成功率较低，建议检查数据源稳定性")

        if metrics.avg_execution_time > 30:
            recommendations.append("执行时间较长，建议优化性能或增加超时时间")

        if metrics.timeout_executions > metrics.total_executions * 0.1:
            recommendations.append("超时频率较高，建议增加超时时间或优化处理逻辑")

        if not recommendations:
            recommendations.append("运行正常")

        return recommendations

    def _summarize_result(self, result: Dict) -> Dict:
        """Create a summary of agent result.

        Args:
            result: Result dictionary to summarize

        Returns:
            Summary dictionary
        """
        if not result:
            return {}

        summary = {}

        if "symbols" in result:
            summary["symbols_count"] = len(result["symbols"])

        if "market_data" in result:
            summary["market_data_size"] = len(result["market_data"])

        if "technical_analysis" in result:
            summary["has_technical_analysis"] = True

        if "fundamental_analysis" in result:
            summary["has_fundamental_analysis"] = True

        return summary


# Global monitor instance
_monitor: Optional[AgentMonitor] = None


def get_monitor() -> AgentMonitor:
    """Get the global monitor instance.

    Returns:
        Global AgentMonitor instance
    """
    global _monitor
    if _monitor is None:
        _monitor = AgentMonitor()
    return _monitor


def reset_monitor() -> None:
    """Reset the global monitor instance."""
    global _monitor
    _monitor = None
