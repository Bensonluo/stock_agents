#!/usr/bin/env python3
"""Simple test script to verify the stock agent system is working."""

import asyncio
import sys
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, ".")


async def main():
    """Run a simple test of the system."""
    print("=" * 60)
    print("Stock Analysis Multi-Agent System - Test Script")
    print("=" * 60)
    print()

    # Test 1: Import modules
    print("Test 1: Importing modules...")
    try:
        from app.orchestration import create_initial_state, get_workflow_summary
        from app.monitoring import get_monitor
        from app.resilience import get_retry_manager, get_circuit_breaker_registry
        print("  ✓ All modules imported successfully")
    except Exception as e:
        print(f"  ✗ Import failed: {e}")
        return False

    print()

    # Test 2: Create initial state
    print("Test 2: Creating initial state...")
    try:
        state = create_initial_state(
            query="Test analysis",
            symbols=["AAPL"],
            max_retries=2,
            timeout_per_agent=60,
        )
        print(f"  ✓ State created with {len(state['symbols'])} symbols")
    except Exception as e:
        print(f"  ✗ State creation failed: {e}")
        return False

    print()

    # Test 3: Test monitoring
    print("Test 3: Testing monitoring system...")
    try:
        monitor = get_monitor()
        monitor.on_agent_start("test_agent", state)
        monitor.on_agent_success("test_agent", 1.5)

        health = monitor.get_agent_health("test_agent")
        print(f"  ✓ Monitoring working (health score: {health['health_score']:.1f})")
    except Exception as e:
        print(f"  ✗ Monitoring test failed: {e}")
        return False

    print()

    # Test 4: Test resilience
    print("Test 4: Testing resilience patterns...")
    try:
        retry_manager = get_retry_manager()
        circuit_registry = get_circuit_breaker_registry()

        # Test circuit breaker
        circuit_registry.record_success("test_agent", 1.0)
        stats = circuit_registry.get_all_stats()
        print(f"  ✓ Circuit breaker registered: {len(stats)} circuits")
    except Exception as e:
        print(f"  ✗ Resilience test failed: {e}")
        return False

    print()

    # Test 5: Test workflow summary
    print("Test 5: Getting workflow summary...")
    try:
        summary = get_workflow_summary()
        print(f"  ✓ Workflow has {len(summary['agents'])} agents:")
        for agent in summary['agents']:
            print(f"    - {agent}")
    except Exception as e:
        print(f"  ✗ Workflow summary failed: {e}")
        return False

    print()

    # Test 6: Test data service (optional - requires network)
    print("Test 6: Testing data service (may require network)...")
    try:
        from app.services import DataService

        data_service = DataService()
        quote = await data_service.get_quote("AAPL")
        if quote and quote.get("price"):
            print(f"  ✓ AAPL price: ${quote.get('price', 0):.2f}")
        else:
            print(f"  ⚠ Data service returned empty response (network issue?)")
    except Exception as e:
        print(f"  ⚠ Data service test skipped: {e}")

    print()

    # Summary
    print("=" * 60)
    print("Test Summary: CORE SYSTEM FUNCTIONAL")
    print("=" * 60)
    print()
    print("To run the full API server:")
    print("  poetry install")
    print("  poetry run uvicorn app.main:app --reload")
    print()
    print("Or with Docker:")
    print("  docker-compose up")
    print()
    print("API will be available at: http://localhost:8000")
    print("API docs: http://localhost:8000/docs")
    print()

    return True


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
