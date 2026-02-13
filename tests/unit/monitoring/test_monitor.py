"""Unit tests for monitoring module."""

import pytest

from app.monitoring import AgentMonitor, AgentMetrics, AlertSeverity
from app.orchestration.state import create_initial_state


@pytest.fixture
def monitor():
    """Get a fresh monitor instance."""
    return AgentMonitor()


@pytest.fixture
def sample_state():
    """Sample state for testing."""
    return create_initial_state(
        query="Test",
        symbols=["AAPL"],
        max_retries=3,
    )


class TestAgentMonitor:
    """Tests for AgentMonitor class."""

    def test_register_agent(self, monitor):
        """Test agent registration."""
        monitor.register_agent("test_agent")
        assert "test_agent" in monitor.metrics
        assert isinstance(monitor.metrics["test_agent"], AgentMetrics)

    def test_on_agent_start(self, monitor, sample_state):
        """Test on_agent_start callback."""
        monitor.on_agent_start("test_agent", sample_state)

        assert "test_agent" in monitor.metrics
        assert len(monitor.event_log) == 1
        assert monitor.event_log[0].event_type == "agent_start"

    def test_on_agent_success(self, monitor):
        """Test on_agent_success callback."""
        monitor.on_agent_success("test_agent", 5.5)

        metrics = monitor.metrics["test_agent"]
        assert metrics.total_executions == 1
        assert metrics.successful_executions == 1
        assert metrics.avg_execution_time == 5.5

    def test_on_agent_failure(self, monitor):
        """Test on_agent_failure callback."""
        monitor.on_agent_failure(
            "test_agent",
            "Test error",
            3.0,
            error_type="TestError",
        )

        metrics = monitor.metrics["test_agent"]
        assert metrics.total_executions == 1
        assert metrics.failed_executions == 1
        assert metrics.last_error is not None

    def test_on_agent_timeout(self, monitor):
        """Test on_agent_timeout callback."""
        monitor.on_agent_timeout("test_agent", 300)

        metrics = monitor.metrics["test_agent"]
        assert metrics.total_executions == 1
        assert metrics.timeout_executions == 1

    def test_get_agent_health(self, monitor):
        """Test get_agent_health method."""
        monitor.on_agent_success("test_agent", 5.0)
        monitor.on_agent_success("test_agent", 10.0)
        monitor.on_agent_failure("test_agent", "Test", 2.0, "TestError")

        health = monitor.get_agent_health("test_agent")

        assert health["agent"] == "test_agent"
        assert health["total_executions"] == 3
        assert health["successful_executions"] == 2
        assert health["failed_executions"] == 1

    def test_get_system_overview(self, monitor):
        """Test get_system_overview method."""
        monitor.on_agent_success("agent1", 5.0)
        monitor.on_agent_success("agent2", 10.0)
        monitor.on_agent_failure("agent1", "Test", 2.0, "TestError")

        overview = monitor.get_system_overview()

        assert overview["total_agents"] == 2
        assert overview["total_executions"] == 3
        assert overview["total_successful"] == 2
        assert overview["total_failed"] == 1

    def test_add_alert_handler(self, monitor):
        """Test adding alert handler."""
        called = []

        def handler(alert):
            called.append(alert)

        monitor.add_alert_handler(handler)
        monitor.alert_thresholds = {"success_rate": 0.5}

        # Trigger failure that should create alert
        for _ in range(5):
            monitor.on_agent_failure("test_agent", "Test", 1.0, "TestError")

        # Handler should have been called (if alert threshold triggered)
        assert len(monitor.alert_handlers) == 1


class TestAgentMetrics:
    """Tests for AgentMetrics class."""

    def test_initial_state(self):
        """Test initial state of metrics."""
        metrics = AgentMetrics(agent_name="test")

        assert metrics.agent_name == "test"
        assert metrics.total_executions == 0
        assert metrics.successful_executions == 0
        assert metrics.failed_executions == 0
        assert metrics.success_rate == 1.0
        assert metrics.health_score == 100.0

    def test_record_execution_success(self):
        """Test recording successful execution."""
        metrics = AgentMetrics(agent_name="test")

        metrics.record_execution(success=True, execution_time=5.0)

        assert metrics.total_executions == 1
        assert metrics.successful_executions == 1
        assert metrics.avg_execution_time == 5.0
        assert metrics.min_execution_time == 5.0
        assert metrics.max_execution_time == 5.0

    def test_record_execution_failure(self):
        """Test recording failed execution."""
        metrics = AgentMetrics(agent_name="test")

        metrics.record_execution(
            success=False,
            execution_time=3.0,
            error_type="TestError",
            error_message="Test error message",
        )

        assert metrics.total_executions == 1
        assert metrics.failed_executions == 1
        assert metrics.last_error is not None
        assert metrics.last_error["type"] == "TestError"

    def test_calculate_success_rate(self):
        """Test success rate calculation."""
        metrics = AgentMetrics(agent_name="test")

        metrics.record_execution(success=True, execution_time=1.0)
        metrics.record_execution(success=True, execution_time=1.0)
        metrics.record_execution(success=False, execution_time=1.0)

        assert metrics.calculate_success_rate() == 2/3

    def test_calculate_health_score(self):
        """Test health score calculation."""
        metrics = AgentMetrics(agent_name="test")

        # All successful = high health
        for _ in range(10):
            metrics.record_execution(success=True, execution_time=1.0)

        health = metrics.calculate_health_score()
        assert health > 80

    def test_update_percentiles(self):
        """Test percentile update."""
        metrics = AgentMetrics(agent_name="test")

        # Add some execution times
        for i in range(100):
            metrics.record_execution(success=True, execution_time=float(i))

        metrics.update_percentiles()

        assert metrics.p95_execution_time > 0
        assert metrics.p99_execution_time > 0
        assert metrics.p99_execution_time >= metrics.p95_execution_time

    def test_get_summary(self):
        """Test get_summary method."""
        metrics = AgentMetrics(agent_name="test")

        metrics.record_execution(success=True, execution_time=5.0)

        summary = metrics.get_summary()

        assert summary["agent_name"] == "test"
        assert summary["total_executions"] == 1
        assert "status" in summary
