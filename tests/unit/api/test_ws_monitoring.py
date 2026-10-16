"""WebSocket monitoring endpoint characterization — app/api/routes/websocket.py
had zero direct tests despite carrying the endpoint's whole security surface
(message-size cap, per-connection rate limit, per-IP connection cap, strict
Pydantic message validation, generic error responses).

Recon surfaced two production bugs that these tests pin as fixed:

1. Double accept — the endpoint called ``websocket.accept()`` and then
   ``ConnectionManager.connect()`` accepted a second time; the ASGI state
   machine rejects the second ``websocket.accept``, so the very first
   connection died before ``initial_state`` was ever sent.
2. IP-slot erosion — the ``finally`` block released the per-IP slot even for
   connections that were *rejected* by the cap (a slot they never acquired).
   Every rejected connection decremented a live slot, so after N rejections
   the limit stopped blocking anything (verified empirically: with 5 slots
   held, the 6th was rejected but the 7th got through).

The endpoint tests mount only the websocket router on a fresh FastAPI app
(same pattern as test_rate_limit.py) — no app.main side effects. Starlette's
TestClient sessions each run their own portal; module-global state
(``_ip_connections``) is reset around every test and the manager singleton is
reset in teardown so nothing leaks into neighbouring test modules.
"""

from __future__ import annotations

import contextlib
import time

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from app.api.routes import websocket as ws
from app.api.websocket.manager import reset_manager

URL = "/api/ws/monitoring"


@pytest.fixture(autouse=True)
def _reset_module_state():
    ws._ip_connections.clear()
    yield
    ws._ip_connections.clear()
    reset_manager()


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(ws.router, prefix="/api")
    return TestClient(app)


def _drain_until_disconnect(session) -> None:
    """Consume queued server messages until the close frame raises."""
    with pytest.raises(WebSocketDisconnect):
        while True:
            session.receive_json()


class _FakeWS:
    """Header/client stub for the pure IP-extraction helper."""

    def __init__(self, headers=None, client=None):
        self.headers = headers or {}
        self.client = client


class _RecordingWS:
    """Records send_json/close calls for the pure message helpers."""

    def __init__(self):
        self.sent: list[dict] = []
        self.closed: tuple | None = None

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def close(self, code=None, reason=None) -> None:
        self.closed = (code, reason)


class TestClientMessageValidation:
    """Strict Literal typing is the injection guard for client messages."""

    @pytest.mark.parametrize("message_type", ["subscribe", "unsubscribe", "set_filters", "ping"])
    def test_valid_types_accepted_with_default_data(self, message_type) -> None:
        dumped = ws.ClientMessage(type=message_type).model_dump()
        assert dumped == {"type": message_type, "data": {}}

    def test_unknown_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ws.ClientMessage(type="inject", data={})

    def test_non_dict_data_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ws.ClientMessage(type="ping", data="not-a-dict")


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_allows_up_to_max_then_blocks(self) -> None:
        limiter = ws.WebSocketRateLimiter(max_messages=2)

        assert await limiter.check_limit() is True
        assert await limiter.check_limit() is True
        assert await limiter.check_limit() is False
        assert await limiter.get_remaining() == 0

    @pytest.mark.asyncio
    async def test_window_eviction_restores_budget(self, monkeypatch) -> None:
        monkeypatch.setattr(ws, "RATE_LIMIT_WINDOW", 0.05)
        limiter = ws.WebSocketRateLimiter(max_messages=1)

        assert await limiter.check_limit() is True
        assert await limiter.check_limit() is False
        time.sleep(0.06)  # push the single timestamp out of the window
        assert await limiter.check_limit() is True


class TestIpConnectionCap:
    @pytest.mark.asyncio
    async def test_acquire_up_to_cap_then_block_and_release(self) -> None:
        for _ in range(ws.MAX_CONNECTIONS_PER_IP):
            assert await ws._can_accept_ip("1.2.3.4") is True
        assert await ws._can_accept_ip("1.2.3.4") is False

        await ws._release_ip("1.2.3.4")
        assert await ws._can_accept_ip("1.2.3.4") is True

    @pytest.mark.asyncio
    async def test_release_to_zero_deletes_the_key(self) -> None:
        await ws._can_accept_ip("1.2.3.4")
        await ws._release_ip("1.2.3.4")

        assert "1.2.3.4" not in ws._ip_connections  # no stale zero-count leak

    @pytest.mark.asyncio
    async def test_release_on_never_acquired_ip_is_safe_noop(self) -> None:
        await ws._release_ip("9.9.9.9")

        assert ws._ip_connections == {}


class TestGetClientIp:
    def test_forwarded_for_takes_first_ip(self) -> None:
        fake = _FakeWS(headers={"x-forwarded-for": "1.1.1.1, 2.2.2.2"})
        assert ws._get_client_ip(fake) == "1.1.1.1"

    def test_real_ip_fallback(self) -> None:
        fake = _FakeWS(headers={"x-real-ip": "3.3.3.3"})
        assert ws._get_client_ip(fake) == "3.3.3.3"

    def test_socket_peer_fallback(self) -> None:
        fake = _FakeWS(client=type("Peer", (), {"host": "127.0.0.1"})())
        assert ws._get_client_ip(fake) == "127.0.0.1"

    def test_unknown_when_nothing_available(self) -> None:
        assert ws._get_client_ip(_FakeWS()) == "unknown"


class TestErrorResponse:
    @pytest.mark.asyncio
    async def test_error_without_close_sends_generic_envelope(self) -> None:
        fake = _RecordingWS()

        await ws._send_error_response(fake, "Invalid JSON format")

        assert fake.closed is None
        assert fake.sent[-1]["type"] == "error"
        assert fake.sent[-1]["data"]["message"] == "Invalid JSON format"

    @pytest.mark.asyncio
    async def test_error_with_close_uses_policy_violation_code(self) -> None:
        fake = _RecordingWS()

        await ws._send_error_response(fake, "Message size exceeds maximum allowed", close=True)

        assert fake.sent == []  # no JSON sent on the close path
        assert fake.closed == (
            status.WS_1008_POLICY_VIOLATION,
            "Message size exceeds maximum allowed",
        )


class TestHandleClientMessage:
    @pytest.mark.asyncio
    async def test_subscribe_updates_only_provided_fields(self) -> None:
        fake = _RecordingWS()
        subscription = ws.ClientSubscription(agent_names={"technical_agent"})

        await ws.handle_client_message(
            {"type": "subscribe", "data": {"min_severity": "high"}}, fake, subscription
        )

        assert subscription.agent_names == {"technical_agent"}  # untouched
        assert subscription.min_severity == "high"
        reply = fake.sent[-1]
        assert reply["type"] == "subscription_updated"
        assert reply["data"] == {
            "agent_names": ["technical_agent"],
            "event_types": [],
            "min_severity": "high",
        }

    @pytest.mark.asyncio
    async def test_unsubscribe_clears_all_filters(self) -> None:
        fake = _RecordingWS()
        subscription = ws.ClientSubscription(
            agent_names={"a"}, event_types={"agent_failure"}, min_severity="high"
        )

        await ws.handle_client_message({"type": "unsubscribe"}, fake, subscription)

        assert subscription.agent_names == set()
        assert subscription.event_types == set()
        assert subscription.min_severity == "low"
        assert fake.sent[-1]["type"] == "subscription_cleared"

    @pytest.mark.asyncio
    async def test_set_filters_replaces_absent_keys_with_empty(self) -> None:
        fake = _RecordingWS()
        subscription = ws.ClientSubscription(agent_names={"old"}, event_types={"old"})

        await ws.handle_client_message({"type": "set_filters", "data": {}}, fake, subscription)

        assert subscription.agent_names == set()
        assert subscription.event_types == set()
        assert fake.sent[-1]["type"] == "filters_updated"

    @pytest.mark.asyncio
    async def test_ping_gets_pong(self) -> None:
        fake = _RecordingWS()

        await ws.handle_client_message({"type": "ping"}, fake, ws.ClientSubscription())

        assert fake.sent[-1]["type"] == "pong"

    @pytest.mark.asyncio
    async def test_unknown_type_is_silently_ignored(self) -> None:
        fake = _RecordingWS()

        await ws.handle_client_message({"type": "exploit"}, fake, ws.ClientSubscription())

        assert fake.sent == []


class TestEndpointHandshake:
    def test_initial_state_first_message_with_temp_thread_id(self, client) -> None:
        with client.websocket_connect(URL) as session:
            first = session.receive_json()

        assert first["type"] == "initial_state"
        assert first["data"]["thread_id"].startswith("temp_")
        assert {
            "system_overview",
            "agent_metrics",
            "circuit_breakers",
            "active_alerts",
            "thread_id",
        } <= set(first["data"])

    def test_thread_id_query_echoes_without_temp_prefix(self, client) -> None:
        with client.websocket_connect(f"{URL}?thread_id=analysis-123") as session:
            first = session.receive_json()

        assert first["data"]["thread_id"] == "analysis-123"

    def test_ws_connections_endpoint_shape(self, client) -> None:
        response = client.get("/api/ws/connections")

        assert response.status_code == 200
        body = response.json()
        assert body["active_connections"] == 0
        assert body["active_thread_ids"] == []
        assert "timestamp" in body


class TestEndpointProtocol:
    def test_ping_pong_roundtrip(self, client) -> None:
        with client.websocket_connect(URL) as session:
            session.receive_json()  # initial_state

            session.send_json({"type": "ping"})

            assert session.receive_json()["type"] == "pong"

    def test_subscribe_gets_ack_then_system_update(self, client) -> None:
        with client.websocket_connect(URL) as session:
            session.receive_json()  # initial_state

            session.send_json(
                {
                    "type": "subscribe",
                    "data": {"agent_names": ["data_agent"], "min_severity": "medium"},
                }
            )

            ack = session.receive_json()
            assert ack["type"] == "subscription_updated"
            assert ack["data"]["agent_names"] == ["data_agent"]
            assert session.receive_json()["type"] == "system_update"

    def test_invalid_json_gets_error_but_connection_survives(self, client) -> None:
        with client.websocket_connect(URL) as session:
            session.receive_json()  # initial_state

            session.send_text("{not json")
            error = session.receive_json()
            assert error["type"] == "error"
            assert error["data"]["message"] == "Invalid JSON format"

            session.send_json({"type": "ping"})
            assert session.receive_json()["type"] == "pong"  # still alive

    def test_invalid_message_type_gets_generic_error(self, client) -> None:
        with client.websocket_connect(URL) as session:
            session.receive_json()  # initial_state

            session.send_json({"type": "exploit", "data": {}})
            error = session.receive_json()
            assert error["type"] == "error"
            assert error["data"]["message"] == "Invalid message format"


class TestEndpointLimits:
    def test_oversized_message_closes_connection(self, client) -> None:
        with client.websocket_connect(URL) as session:
            session.receive_json()  # initial_state

            session.send_text("x" * (ws.MAX_MESSAGE_SIZE + 1))
            _drain_until_disconnect(session)  # code pinned below via 1008 close

    def test_rate_limit_closes_after_burst(self, client) -> None:
        with client.websocket_connect(URL) as session:
            session.receive_json()  # initial_state

            for _ in range(ws.MAX_MESSAGES_PER_SECOND + 1):
                session.send_json({"type": "ping"})
            _drain_until_disconnect(session)

    def test_per_ip_cap_holds_across_repeated_rejections(self, client) -> None:
        """The erosion pin: a rejected connection must not free a slot it
        never acquired, so the 7th attempt is rejected exactly like the 6th."""
        with contextlib.ExitStack() as stack:
            sessions = []
            for _ in range(ws.MAX_CONNECTIONS_PER_IP):
                session = stack.enter_context(client.websocket_connect(URL))
                session.receive_json()  # initial_state
                sessions.append(session)

            for _attempt in (6, 7):
                with pytest.raises(WebSocketDisconnect) as exc_info:
                    with client.websocket_connect(URL) as rejected:
                        rejected.receive_json()
                assert exc_info.value.code == status.WS_1008_POLICY_VIOLATION
                time.sleep(0.1)  # let the rejected handler's finally settle

            assert ws._ip_connections.get("testclient") == ws.MAX_CONNECTIONS_PER_IP
