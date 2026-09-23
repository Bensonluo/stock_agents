"""Tests for the shared LLM structured-output helper."""

from typing import Literal

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field

from app.utils.llm_json import ainvoke_json, extract_json

pytestmark = pytest.mark.asyncio


class _Panel(BaseModel):
    sentiment: Literal["positive", "negative", "neutral"] = "neutral"
    confidence: int = Field(default=50, ge=0, le=100)


class _FakeLLM:
    """Plain chat model stub: returns fixed content from ainvoke."""

    def __init__(self, content):
        self.content = content
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return AIMessage(content=self.content)


class _StructuredLLM:
    """Native-path stub: with_structured_output returns a schema instance."""

    def __init__(self, result):
        self.result = result

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    async def ainvoke(self, messages):
        return self.result


class _BrokenStructuredLLM:
    """Native path raises; plain ainvoke serves fenced JSON."""

    def __init__(self, content):
        self.content = content
        self.plain_calls = 0

    def with_structured_output(self, schema):
        raise RuntimeError("tool calling unsupported")

    async def ainvoke(self, messages):
        self.plain_calls += 1
        return AIMessage(content=self.content)


class TestExtractJson:
    def test_plain_object(self):
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_fenced_json(self):
        assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_chatter_with_trailing_brace(self):
        # The old first-{-to-last-} slice would grab "} and { more" as JSON.
        text = 'Here you go: {"a": 1, "b": {"c": 2}} — hope that helps {ok}'
        assert extract_json(text) == {"a": 1, "b": {"c": 2}}

    def test_braces_inside_strings(self):
        assert extract_json('{"note": "contains } brace", "x": 1}') == {
            "note": "contains } brace",
            "x": 1,
        }

    def test_escaped_quotes_inside_strings(self):
        assert extract_json('{"note": "say \\"hi\\"", "x": 1}') == {"note": 'say "hi"', "x": 1}

    def test_array_payload(self):
        assert extract_json("prefix [1, 2, 3] suffix") == [1, 2, 3]

    def test_unbalanced_returns_none(self):
        assert extract_json('{"a": 1') is None

    def test_no_json_returns_none(self):
        assert extract_json("no json here") is None

    def test_empty_returns_none(self):
        assert extract_json("") is None
        assert extract_json(None) is None

    def test_invalid_json_returns_none(self):
        assert extract_json("{not valid json}") is None


class TestAinvokeJson:
    async def test_plain_prompt_path(self):
        llm = _FakeLLM('```json\n{"a": 1}\n```')
        result = await ainvoke_json(llm, system="s", user="u")
        assert result == {"a": 1}
        assert len(llm.calls) == 1

    async def test_schema_validated_prompt_path(self):
        llm = _FakeLLM('{"sentiment": "positive", "confidence": 80}')
        result = await ainvoke_json(llm, system="s", user="u", schema=_Panel)
        assert result == {"sentiment": "positive", "confidence": 80}

    async def test_schema_violation_degrades_to_none(self):
        llm = _FakeLLM('{"sentiment": "positive", "confidence": 500}')
        assert await ainvoke_json(llm, system="s", user="u", schema=_Panel) is None

    async def test_native_structured_output_path(self):
        llm = _StructuredLLM(_Panel(sentiment="negative", confidence=70))
        result = await ainvoke_json(llm, system="s", user="u", schema=_Panel)
        assert result == {"sentiment": "negative", "confidence": 70}

    async def test_native_failure_falls_back_to_prompt_json(self):
        llm = _BrokenStructuredLLM('verdict: {"sentiment": "neutral"}')
        result = await ainvoke_json(llm, system="s", user="u", schema=_Panel)
        assert result == {"sentiment": "neutral", "confidence": 50}
        assert llm.plain_calls == 1

    async def test_none_llm_returns_none(self):
        assert await ainvoke_json(None, system="s", user="u") is None

    async def test_ainvoke_failure_returns_none(self):
        class _Exploding:
            async def ainvoke(self, messages):
                raise RuntimeError("endpoint down")

        assert await ainvoke_json(_Exploding(), system="s", user="u") is None

    async def test_unparsable_content_returns_none(self):
        llm = _FakeLLM("the model rambled and never produced JSON")
        assert await ainvoke_json(llm, system="s", user="u") is None

    async def test_list_content_is_joined(self):
        class _MultiPart:
            async def ainvoke(self, messages):
                return AIMessage(content=['{"a": ', "1}"])

        assert await ainvoke_json(_MultiPart(), system="s", user="u") == {"a": 1}
