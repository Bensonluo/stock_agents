"""Admission-control pins for the global analysis capacity guard.

The per-client rate limiter (iteration 169) bounds what ONE client can
request; nothing bounded how many full analysis workflows may run at
once. Each analyze POST is ~162s of multi-agent LLM work — a handful of
concurrent clients stack unbounded pipelines and trip the LLM
provider's own limits even when every client is within its rate budget.
These pins lock the guard itself, request-time admission on all three
analyze routes, and the always-release lifecycle.
"""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api import analysis_capacity as cap
from app.api.routes import agent, analysis
from app.config import Settings


def _full_status(degraded: str | None = None) -> dict:
    return {
        name: ("failed" if name == degraded else "completed")
        for name in (
            "data_collection",
            "technical_analysis",
            "fundamental_analysis",
            "sentiment_analysis",
            "risk_assessment",
            "research_synthesis",
            "decision_making",
            "report_generation",
        )
    }


def _impl_result() -> dict:
    return {
        "agent_status": _full_status(),
        "errors": [],
        "execution_metadata": {},
        "report": {"title": "report"},
    }


@pytest.fixture
def tight_capacity(monkeypatch):
    """Cap of exactly one in-flight analysis, isolated counter.

    The rate limiter is disabled so these tests depend only on capacity
    state (analysis POSTs across the suite share the limiter registry).
    """
    from app.config import settings

    monkeypatch.setattr(settings, "max_concurrent_analyses", 1)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    cap.reset_analysis_capacity()
    yield
    cap.reset_analysis_capacity()


@pytest.fixture
def client():
    app = FastAPI()
    # Same prefixes as app.main so tests hit production-shaped paths.
    app.include_router(analysis.router, prefix="/api/analysis")
    app.include_router(agent.router, prefix="/api")
    with TestClient(app) as c:
        yield c


class TestCapacityGuard:
    def test_admits_up_to_cap_then_503(self, tight_capacity) -> None:
        release = cap.reserve_analysis_slot()
        with pytest.raises(HTTPException) as exc_info:
            cap.reserve_analysis_slot()
        assert exc_info.value.status_code == 503
        release()
        # slot freed -> admission works again
        cap.reserve_analysis_slot()()

    def test_503_carries_retry_after_header(self, tight_capacity) -> None:
        release = cap.reserve_analysis_slot()
        with pytest.raises(HTTPException) as exc_info:
            cap.reserve_analysis_slot()
        assert exc_info.value.headers is not None
        assert "Retry-After" in exc_info.value.headers
        release()

    def test_analysis_slot_releases_on_exception(self, tight_capacity) -> None:
        with pytest.raises(RuntimeError, match="boom"):
            with cap.analysis_slot():
                raise RuntimeError("boom")
        assert cap.in_flight() == 0

    def test_disabled_cap_is_unlimited(self, monkeypatch) -> None:
        from app.config import settings

        monkeypatch.setattr(settings, "max_concurrent_analyses", 0)
        cap.reset_analysis_capacity()
        releases = [cap.reserve_analysis_slot() for _ in range(5)]
        assert cap.in_flight() == 5
        for release in releases:
            release()
        assert cap.in_flight() == 0

    def test_release_never_goes_negative(self, tight_capacity) -> None:
        release = cap.reserve_analysis_slot()
        release()
        release()  # double release must not underflow
        assert cap.in_flight() == 0


class TestSyncRouteAdmission:
    def test_sync_analyze_503_when_full(self, client, tight_capacity) -> None:
        held = cap.reserve_analysis_slot()
        before = set(analysis.workflows)
        response = client.post(
            "/api/analysis/analyze/sync", json={"query": "分析", "symbols": ["AAPL"]}
        )
        assert response.status_code == 503
        assert "detail" in response.json()
        assert set(analysis.workflows) == before  # no half-created state
        held()

    def test_sync_analyze_admits_and_releases(self, client, tight_capacity, monkeypatch) -> None:
        monkeypatch.setattr(
            analysis, "_execute_workflow_impl", AsyncMock(return_value=_impl_result())
        )
        analysis.workflows.pop("capacity-sync", None)
        response = client.post(
            "/api/analysis/analyze/sync", json={"query": "分析", "symbols": ["AAPL"]}
        )
        assert response.status_code == 200
        assert cap.in_flight() == 0  # released after the inline run

    def test_sync_analyze_releases_on_impl_failure(
        self, client, tight_capacity, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            analysis,
            "_execute_workflow_impl",
            AsyncMock(side_effect=RuntimeError("workflow exploded")),
        )
        response = client.post(
            "/api/analysis/analyze/sync", json={"query": "分析", "symbols": ["AAPL"]}
        )
        assert response.status_code == 500
        assert cap.in_flight() == 0  # exception path also releases


class TestBackgroundRouteAdmission:
    def test_analyze_503_when_full_creates_no_workflow(self, client, tight_capacity) -> None:
        held = cap.reserve_analysis_slot()
        before = set(analysis.workflows)
        response = client.post("/api/analysis/analyze", json={"query": "分析", "symbols": ["AAPL"]})
        assert response.status_code == 503
        assert set(analysis.workflows) == before
        held()

    def test_analyze_holds_slot_during_run_and_releases(
        self, client, tight_capacity, monkeypatch
    ) -> None:
        seen: list[int] = []

        async def _spy(*args, **kwargs):
            seen.append(cap.in_flight())
            return _impl_result()

        monkeypatch.setattr(analysis, "_execute_workflow_impl", _spy)
        response = client.post("/api/analysis/analyze", json={"query": "分析", "symbols": ["AAPL"]})
        assert response.status_code == 200
        assert seen == [1]  # the slot is held while the workflow runs
        assert cap.in_flight() == 0  # ...and returned once it finishes

    def test_agent_analyze_503_when_full(self, client, tight_capacity) -> None:
        held = cap.reserve_analysis_slot()
        response = client.post("/api/agent/analyze", json={"query": "分析", "symbols": ["AAPL"]})
        assert response.status_code == 503
        assert "detail" in response.json()
        held()

    def test_agent_analyze_releases_after_background_run(
        self, client, tight_capacity, monkeypatch
    ) -> None:
        monkeypatch.setattr(agent, "_run_analysis", AsyncMock())
        response = client.post("/api/agent/analyze", json={"query": "分析", "symbols": ["AAPL"]})
        assert response.status_code == 200
        assert cap.in_flight() == 0


class TestWiringPins:
    def test_default_cap_is_two(self) -> None:
        assert Settings.model_fields["max_concurrent_analyses"].default == 2

    def test_env_example_documents_the_cap(self) -> None:
        from pathlib import Path

        env_example = Path(__file__).resolve().parents[3] / ".env.example"
        assert "MAX_CONCURRENT_ANALYSES=2" in env_example.read_text()
