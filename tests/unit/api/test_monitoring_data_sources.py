"""Route test: /api/monitoring/data-sources exposes the provider counters.

Same isolated-app fixture pattern as the backtest API tests — the router
under test is mounted alone so no other route's dependencies leak in.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.routes.monitoring as monitoring_route
from app.tools.data.provider_health import record_provider_outcome, reset_provider_health


@pytest.fixture(autouse=True)
def _isolated_counters():
    reset_provider_health()
    yield
    reset_provider_health()


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(monitoring_route.router, prefix="/api/monitoring")
    return TestClient(app)


def test_data_sources_returns_snapshot_shape(client: TestClient) -> None:
    record_provider_outcome("yfinance", "ok")
    record_provider_outcome("akshare-cn", "fail", "boom")

    response = client.get("/api/monitoring/data-sources")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"providers", "generated_at"}
    assert body["providers"]["yfinance"]["ok"] == 1
    assert body["providers"]["akshare-cn"]["fail"] == 1
    assert body["providers"]["akshare-cn"]["last_error"] == "boom"


def test_data_sources_empty_snapshot_is_still_200(client: TestClient) -> None:
    response = client.get("/api/monitoring/data-sources")

    assert response.status_code == 200
    assert response.json()["providers"] == {}


def test_monitoring_reset_returns_iso_timestamp(client: TestClient) -> None:
    """POST /reset once bound its timestamp field to the module logger object,
    which jsonable_encoder cannot serialize -- the endpoint 500ed on every
    call. The timestamp must be a parseable ISO string."""
    response = client.post("/api/monitoring/reset")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "reset"
    datetime.fromisoformat(body["timestamp"])
