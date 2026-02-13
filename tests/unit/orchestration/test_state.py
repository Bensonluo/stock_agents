"""Unit tests for orchestration module."""

import pytest

from app.orchestration.state import (
    add_agent_output,
    add_error,
    create_initial_state,
    get_agent_errors,
    get_retry_count,
    get_agent_status,
    has_errors,
    set_agent_status,
    should_retry,
)


class TestAgentState:
    """Tests for AgentState management functions."""

    def test_create_initial_state(self):
        """Test creating initial state."""
        state = create_initial_state(
            query="Test query",
            symbols=["AAPL", "MSFT"],
            max_retries=3,
            timeout_per_agent=300,
        )

        assert state["query"] == "Test query"
        assert state["symbols"] == ["AAPL", "MSFT"]
        assert state["max_retries"] == 3
        assert state["timeout_per_agent"] == 300
        assert state["agent_outputs"] == []
        assert state["errors"] == []
        assert state["retry_count"] == {}
        assert state["agent_status"] == {}

    def test_set_agent_status(self):
        """Test setting agent status."""
        state = create_initial_state(
            query="Test",
            symbols=["AAPL"],
            max_retries=3,
        )

        state = set_agent_status(state, "test_agent", "running")

        assert state["agent_status"]["test_agent"] == "running"

    def test_get_agent_status(self):
        """Test getting agent status."""
        state = create_initial_state(
            query="Test",
            symbols=["AAPL"],
            max_retries=3,
        )

        status = get_agent_status(state, "test_agent")
        assert status == "pending"  # Default for unset agents

        state = set_agent_status(state, "test_agent", "completed")
        status = get_agent_status(state, "test_agent")
        assert status == "completed"

    def test_add_agent_output(self):
        """Test adding agent output."""
        state = create_initial_state(
            query="Test",
            symbols=["AAPL"],
            max_retries=3,
        )

        result = {"test": "data"}
        state = add_agent_output(state, "test_agent", result)

        assert len(state["agent_outputs"]) == 1
        assert state["agent_outputs"][0]["agent"] == "test_agent"
        assert state["agent_outputs"][0]["result"] == result

    def test_add_error(self):
        """Test adding error."""
        state = create_initial_state(
            query="Test",
            symbols=["AAPL"],
            max_retries=3,
        )

        state = add_error(
            state,
            "test_agent",
            "TestError",
            "Test error message",
            retryable=True,
        )

        assert len(state["errors"]) == 1
        assert state["errors"][0]["agent"] == "test_agent"
        assert state["errors"][0]["type"] == "TestError"
        assert state["retry_count"]["test_agent"] == 1

    def test_get_retry_count(self):
        """Test getting retry count."""
        state = create_initial_state(
            query="Test",
            symbols=["AAPL"],
            max_retries=3,
        )

        assert get_retry_count(state, "test_agent") == 0

        state = add_error(state, "test_agent", "TestError", "Test", True)
        assert get_retry_count(state, "test_agent") == 1

    def test_should_retry(self):
        """Test should_retry logic."""
        state = create_initial_state(
            query="Test",
            symbols=["AAPL"],
            max_retries=3,
        )

        assert should_retry(state, "test_agent")

        # Add retryable errors
        for i in range(3):
            state = add_error(state, "test_agent", "TestError", "Test", True)
            if i < 2:
                assert should_retry(state, "test_agent")
            else:
                assert not should_retry(state, "test_agent")

    def test_get_agent_errors(self):
        """Test getting agent errors."""
        state = create_initial_state(
            query="Test",
            symbols=["AAPL"],
            max_retries=3,
        )

        state = add_error(state, "agent1", "Error1", "Test1", True)
        state = add_error(state, "agent2", "Error2", "Test2", True)

        agent1_errors = get_agent_errors(state, "agent1")
        assert len(agent1_errors) == 1
        assert agent1_errors[0]["type"] == "Error1"

        agent2_errors = get_agent_errors(state, "agent2")
        assert len(agent2_errors) == 1

    def test_has_errors(self):
        """Test has_errors function."""
        state = create_initial_state(
            query="Test",
            symbols=["AAPL"],
            max_retries=3,
        )

        assert not has_errors(state)

        state = add_error(state, "test_agent", "TestError", "Test", True)
        assert has_errors(state)
        assert has_errors(state, "test_agent")
        assert not has_errors(state, "other_agent")

    def test_execution_summary(self):
        """Test execution summary."""
        from app.orchestration.state import get_execution_summary

        state = create_initial_state(
            query="Test",
            symbols=["AAPL", "MSFT"],
            max_retries=3,
        )

        state = set_agent_status(state, "agent1", "completed")
        state = set_agent_status(state, "agent2", "failed")
        state = add_error(state, "agent2", "TestError", "Test", True)

        summary = get_execution_summary(state)

        assert "workflow_id" in summary
        assert summary["total_agents"] == 2
        assert summary["completed_agents"] == ["agent1"]
        assert summary["failed_agents"] == ["agent2"]
        assert summary["total_errors"] == 1
