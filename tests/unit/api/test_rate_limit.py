"""In-process sliding-window rate limiting for the expensive POST endpoints.

The product is publicly exposed (Live Demo) and every analyze POST spends
~162s of real multi-agent LLM work; every backtest POST burns CPU on the
bounded executor pool. These tests pin the limiter math (including the
memory bound against client-key floods), the client-key trust model
(right-most X-Forwarded-For, else the socket peer), the FastAPI dependency
behavior (429 + Retry-After), and the structural attachment of the
dependency to all seven expensive POSTs on the real routers.
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.api import rate_limit as rl
from app.api.routes import agent, analysis, backtest
from app.config import settings


@pytest.fixture()
def tight_limits(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_analysis_limit", 2)
    monkeypatch.setattr(settings, "rate_limit_analysis_window_seconds", 600)
    monkeypatch.setattr(settings, "rate_limit_backtest_limit", 3)
    monkeypatch.setattr(settings, "rate_limit_backtest_window_seconds", 600)
    rl.reset_rate_limiter()
    yield
    rl.reset_rate_limiter()


@pytest.fixture()
def client(tight_limits):
    app = FastAPI()

    @app.post("/analysis-stub", dependencies=[Depends(rl.rate_limit("analysis"))])
    def analysis_stub():
        return {"ok": True}

    @app.post("/backtest-stub", dependencies=[Depends(rl.rate_limit("backtest"))])
    def backtest_stub():
        return {"ok": True}

    return TestClient(app)


def _make_request(headers=None, client=("1.2.3.4", 1234)):
    """A real starlette Request from a raw ASGI scope (no server needed)."""
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": client,
    }
    return Request(scope)


def _post_buckets(router):
    """POST paths -> the rate-limit buckets attached to each (structural pin)."""
    out = {}
    for route in router.routes:
        methods = getattr(route, "methods", None) or set()
        if "POST" in methods:
            buckets = [
                getattr(dep.dependency, "rate_limit_bucket", None) for dep in route.dependencies
            ]
            out[route.path] = [b for b in buckets if b is not None]
    return out


class TestSlidingWindowLimiter:
    def test_allows_up_to_limit_then_rejects(self) -> None:
        limiter = rl.SlidingWindowLimiter(limit=2, window_seconds=100.0)
        assert limiter.check("k", now=0.0) is None
        assert limiter.check("k", now=1.0) is None
        assert limiter.check("k", now=2.0) is not None

    def test_window_slides_old_hits_expire(self) -> None:
        limiter = rl.SlidingWindowLimiter(limit=2, window_seconds=100.0)
        limiter.check("k", now=0.0)
        limiter.check("k", now=1.0)
        # At t=101 every hit older than the window has expired; only one hit
        # remains, so a third hit is allowed again.
        assert limiter.check("k", now=101.0) is None

    def test_retry_after_bounds(self) -> None:
        limiter = rl.SlidingWindowLimiter(limit=1, window_seconds=100.0)
        limiter.check("k", now=0.0)
        retry_after = limiter.check("k", now=10.0)
        assert retry_after is not None
        assert 0 < retry_after <= 90.0

    def test_keys_are_isolated(self) -> None:
        limiter = rl.SlidingWindowLimiter(limit=2, window_seconds=100.0)
        limiter.check("a", now=0.0)
        limiter.check("a", now=1.0)
        assert limiter.check("a", now=2.0) is not None
        assert limiter.check("b", now=2.0) is None

    def test_rejected_hit_does_not_extend_window(self) -> None:
        limiter = rl.SlidingWindowLimiter(limit=1, window_seconds=100.0)
        limiter.check("k", now=0.0)
        assert limiter.check("k", now=50.0) is not None  # rejected, NOT recorded
        # Had the rejection been recorded, the t=50 hit would still be inside
        # the window here; because it was not, the original hit has expired.
        assert limiter.check("k", now=100.5) is None

    def test_flood_of_distinct_keys_is_bounded(self) -> None:
        limiter = rl.SlidingWindowLimiter(limit=1, window_seconds=100.0)
        limiter._MAX_TRACKED_KEYS = 3  # shrink the cap for the test
        for i in range(5):
            assert limiter.check(f"flood-{i}", now=float(i)) is None
        assert len(limiter._hits) <= 3

    def test_prune_drops_fully_expired_keys_first(self) -> None:
        limiter = rl.SlidingWindowLimiter(limit=1, window_seconds=100.0)
        limiter._MAX_TRACKED_KEYS = 2
        limiter.check("old", now=0.0)  # fully expired by t=200
        limiter.check("mid", now=150.0)  # still inside the window at t=200
        limiter.check("new", now=200.0)  # over cap -> prune drops "old" first
        assert "old" not in limiter._hits
        assert "mid" in limiter._hits
        assert "new" in limiter._hits


class TestClientKey:
    def test_rightmost_xff_entry_wins(self) -> None:
        req = _make_request({"X-Forwarded-For": "1.1.1.1, 2.2.2.2"})
        assert rl._client_key(req) == "2.2.2.2"

    def test_no_xff_falls_back_to_socket_peer(self) -> None:
        req = _make_request()
        assert rl._client_key(req) == "1.2.3.4"

    def test_no_client_reports_unknown(self) -> None:
        req = _make_request(client=None)
        assert rl._client_key(req) == "unknown"

    def test_xff_whitespace_is_tolerated(self) -> None:
        req = _make_request({"X-Forwarded-For": "1.1.1.1 , 2.2.2.2 "})
        assert rl._client_key(req) == "2.2.2.2"

    def test_empty_xff_falls_back_to_socket_peer(self) -> None:
        req = _make_request({"X-Forwarded-For": ""})
        assert rl._client_key(req) == "1.2.3.4"


class TestRouteLevel:
    def test_429_with_retry_after_after_limit(self, client) -> None:
        assert client.post("/analysis-stub").status_code == 200
        assert client.post("/analysis-stub").status_code == 200

        r = client.post("/analysis-stub")
        assert r.status_code == 429
        assert r.headers["retry-after"].isdigit()
        assert int(r.headers["retry-after"]) > 0
        assert isinstance(r.json()["detail"], str)

    def test_rightmost_xff_is_the_client_key(self, client) -> None:
        # Two posts whose right-most XFF entry is 2.2.2.2 exhaust that key.
        client.post("/analysis-stub", headers={"X-Forwarded-For": "1.1.1.1, 2.2.2.2"})
        client.post("/analysis-stub", headers={"X-Forwarded-For": "2.2.2.2"})
        # Same right-most entry from any upstream chain -> 429; a different
        # client key is untouched.
        assert (
            client.post(
                "/analysis-stub", headers={"X-Forwarded-For": "9.9.9.9, 2.2.2.2"}
            ).status_code
            == 429
        )
        assert (
            client.post("/analysis-stub", headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 200
        )

    def test_no_xff_keys_by_socket_peer(self, client) -> None:
        # TestClient's socket peer is "testclient" for all bare posts.
        assert client.post("/analysis-stub").status_code == 200
        assert client.post("/analysis-stub").status_code == 200
        assert client.post("/analysis-stub").status_code == 429
        # A distinct XFF key is unaffected by the peer-key exhaustion.
        assert (
            client.post("/analysis-stub", headers={"X-Forwarded-For": "3.3.3.3"}).status_code == 200
        )

    def test_disabled_toggle_unlimited(self, client, monkeypatch) -> None:
        monkeypatch.setattr(settings, "rate_limit_enabled", False)
        for _ in range(10):
            assert client.post("/analysis-stub").status_code == 200

    def test_buckets_are_independent(self, client) -> None:
        headers = {"X-Forwarded-For": "5.5.5.5"}
        assert client.post("/analysis-stub", headers=headers).status_code == 200
        assert client.post("/analysis-stub", headers=headers).status_code == 200
        assert client.post("/analysis-stub", headers=headers).status_code == 429
        # The same client still has its full backtest budget — and it is a
        # real budget (the 4th backtest post exhausts it).
        for _ in range(3):
            assert client.post("/backtest-stub", headers=headers).status_code == 200
        assert client.post("/backtest-stub", headers=headers).status_code == 429

    def test_changed_limit_rebuilds_bucket_fresh(self, client, monkeypatch) -> None:
        headers = {"X-Forwarded-For": "6.6.6.6"}
        client.post("/analysis-stub", headers=headers)
        client.post("/analysis-stub", headers=headers)
        assert client.post("/analysis-stub", headers=headers).status_code == 429
        # Raising the limit rebuilds the bucket with the new budget.
        monkeypatch.setattr(settings, "rate_limit_analysis_limit", 4)
        assert client.post("/analysis-stub", headers=headers).status_code == 200


class TestWiringPins:
    def test_analysis_routes_carry_analysis_bucket(self) -> None:
        assert _post_buckets(analysis.router) == {
            "/analyze": ["analysis"],
            "/analyze/sync": ["analysis"],
        }

    def test_agent_route_carries_analysis_bucket(self) -> None:
        pins = _post_buckets(agent.router)
        assert len(pins) == 1
        path, buckets = next(iter(pins.items()))
        assert path.endswith("/analyze")
        assert buckets == ["analysis"]

    def test_backtest_routes_carry_backtest_bucket(self) -> None:
        assert _post_buckets(backtest.router) == {
            "/run": ["backtest"],
            "/v2/run": ["backtest"],
            "/v2/walkforward": ["backtest"],
            "/v2/calibrate": ["backtest"],
        }
