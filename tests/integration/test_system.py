"""Integration tests for the stock analysis system."""

import pytest

from app.api.dependencies import get_orchestrator
from app.orchestration import MultiAgentOrchestrator


class TestOrchestratorIntegration:
    """Integration tests for the orchestrator."""

    @pytest.mark.asyncio
    async def test_full_workflow_execution(self):
        """Test full workflow execution with real data fetching."""
        orchestrator = get_orchestrator()

        # Test with a single stock
        result = await orchestrator.execute_workflow(
            query="Analyze AAPL stock",
            symbols=["AAPL"],
            thread_id="test-workflow-001",
            max_retries=2,
            timeout_per_agent=60,
        )

        assert result is not None
        assert "market_data" in result
        assert "technical_analysis" in result
        assert "fundamental_analysis" in result
        assert "sentiment_analysis" in result
        assert "risk_assessment" in result
        assert "decision" in result
        assert "report" in result

    @pytest.mark.asyncio
    async def test_workflow_with_multiple_symbols(self):
        """Test workflow with multiple symbols."""
        orchestrator = get_orchestrator()

        result = await orchestrator.execute_workflow(
            query="Compare tech stocks",
            symbols=["AAPL", "MSFT"],
            thread_id="test-workflow-002",
        )

        assert result is not None
        # Should have data for both symbols
        market_data = result.get("market_data", {})
        assert len(market_data) > 0

    @pytest.mark.asyncio
    async def test_workflow_status_tracking(self):
        """Test workflow status tracking."""
        orchestrator = get_orchestrator()

        # Start a workflow
        result = await orchestrator.execute_workflow(
            query="Status test",
            symbols=["AAPL"],
            thread_id="test-workflow-status",
        )

        # Check status
        status = orchestrator.get_workflow_status("test-workflow-status")

        assert status is not None
        assert "thread_id" in status
        assert status["thread_id"] == "test-workflow-status"


class TestDataServiceIntegration:
    """Integration tests for data service."""

    @pytest.mark.asyncio
    async def test_fetch_quote(self):
        """Test fetching real quote data."""
        from app.services import DataService

        service = DataService()

        quote = await service.get_quote("AAPL")

        assert quote is not None
        assert "symbol" in quote
        assert quote["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_fetch_historical_data(self):
        """Test fetching historical data."""
        from app.services import DataService

        service = DataService()

        data = await service.get_historical_data(
            symbol="AAPL",
            period="3mo",
            interval="1d",
        )

        assert data is not None
        assert "dates" in data
        assert len(data["dates"]) > 0
