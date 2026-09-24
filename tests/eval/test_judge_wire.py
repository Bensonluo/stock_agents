"""LLM judge over the real SDK/HTTP path via httpx.MockTransport.

The monkeypatch tests in test_report_eval.py cover judge.py's gating and
parse plumbing. What this adds: ChatOpenAI + the OpenAI SDK serialize the
judge prompt, send it to the configured base URL with the configured key,
and the HTTP response round-trips back into a JudgeVerdict. MockTransport
keeps the full client-side wire format (request shape, headers, response
parsing) while staying offline — real sockets are NOT viable here because
the dev sandbox transparently proxies even loopback (a socket-based mock
gets 502 from the proxy and the server sees nothing), and CI should not
depend on that environment anyway.
"""

from __future__ import annotations

import json

import httpx
import pytest
from langchain_openai import ChatOpenAI as _RealChatOpenAI

from app.config import settings
from app.eval import judge as judge_mod

pytestmark = pytest.mark.asyncio


def _completion_payload(content: str) -> dict:
    return {
        "id": "chatcmpl-mock",
        "object": "chat.completion",
        "created": 1,
        "model": "mock",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


class _Recorder:
    def __init__(self, status: int = 200, content: str = ""):
        self.status = status
        self.content = content
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "mock failure"})
        return httpx.Response(200, json=_completion_payload(self.content))


def _install_transport(monkeypatch: pytest.MonkeyPatch, recorder: _Recorder) -> None:
    """Route any ChatOpenAI the judge builds through the recording transport."""

    def _patched_chat_openai(**kwargs):
        kwargs["http_async_client"] = httpx.AsyncClient(
            transport=httpx.MockTransport(recorder.handler)
        )
        return _RealChatOpenAI(**kwargs)

    import langchain_openai

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", _patched_chat_openai)


def _enable_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "eval_llm_judge", True)
    monkeypatch.setattr(settings, "zhipuai_api_key", "test-key")


class TestJudgeOverMockTransport:
    async def test_verdict_round_trips_over_the_sdk_wire(self, monkeypatch):
        """Prompt, base URL and key travel; the completion parses back."""
        reply = json.dumps(
            {
                "completeness": 8,
                "groundedness": 7,
                "actionability": 6,
                "risk_awareness": 9,
                "overall": 7,
                "rationale": "solid, evidence-tied",
            }
        )
        recorder = _Recorder(content=reply)
        _install_transport(monkeypatch, recorder)
        _enable_judge(monkeypatch)

        verdict = await judge_mod.judge_report("REPORT BODY 42")

        assert verdict is not None
        assert verdict["overall"] == 7
        assert verdict["risk_awareness"] == 9

        assert recorder.requests, "judge made no HTTP request at all"
        request = recorder.requests[0]
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["Authorization"] == "Bearer test-key"
        # The report text actually traveled to the endpoint under test
        assert b"REPORT BODY 42" in request.read()

    async def test_garbage_reply_degrades_to_none(self, monkeypatch):
        recorder = _Recorder(content="cannot grade this")
        _install_transport(monkeypatch, recorder)
        _enable_judge(monkeypatch)

        assert await judge_mod.judge_report("x") is None
        assert recorder.requests  # genuinely asked, not short-circuited

    async def test_endpoint_500_degrades_to_none(self, monkeypatch):
        """Provider 5xx: judge degrades to None instead of raising."""
        recorder = _Recorder(status=500)
        _install_transport(monkeypatch, recorder)
        _enable_judge(monkeypatch)

        assert await judge_mod.judge_report("x") is None
        assert recorder.requests  # SDK may retry; at least one attempt seen
