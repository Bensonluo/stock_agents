"""Pytest configuration and fixtures."""

import pytest


@pytest.fixture
def sample_symbols():
    """Sample stock symbols for testing."""
    return ["AAPL", "MSFT", "GOOGL"]


@pytest.fixture
def sample_state(sample_symbols):
    """Sample agent state for testing."""
    from app.orchestration.state import create_initial_state

    return create_initial_state(
        query="Test analysis",
        symbols=sample_symbols,
        max_retries=3,
        timeout_per_agent=300,
    )
