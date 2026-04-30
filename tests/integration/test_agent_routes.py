import pytest
from fastapi.testclient import TestClient


def test_agent_analyze_endpoint_returns_thread_id():
    """The agent analyze endpoint must return a thread_id."""
    from app.main import app

    client = TestClient(app)
    response = client.post("/api/agent/analyze", json={
        "query": "Should I buy AAPL?",
        "symbols": ["AAPL"],
    })

    assert response.status_code == 200
    data = response.json()
    assert "thread_id" in data
    assert data["status"] == "processing"


def test_agent_result_not_found():
    """Getting a non-existent result must return 404."""
    from app.main import app

    client = TestClient(app)
    response = client.get("/api/agent/result/nonexistent")

    assert response.status_code == 404
