"""Shared LLM structured-output helper (the single JSON boundary for agents).

Transport and parsing live here; domain validation (evidence constraints,
committee-verdict restating, ...) stays in the calling modules. Two paths:

- native structured output: ``llm.with_structured_output(schema)`` enforces
  the schema at the provider level via tool calling, when the endpoint
  supports it;
- prompt-based fallback: plain ``ainvoke`` + robust JSON extraction
  (balanced-brace scanner that tolerates markdown fences and surrounding
  chatter).

Failures degrade to ``None`` (callers decide their fallback) instead of
raising — matching the pipeline's degrade-by-design policy.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from app.utils.logging import get_logger

logger = get_logger(__name__)


def extract_json(text: str) -> Any:
    """Extract the first balanced JSON object (or array) from LLM output.

    Tolerates markdown fences and surrounding prose — unlike a
    first-``{``-to-last-``}`` slice, which silently breaks when the model
    appends text containing braces.
    """
    stripped = (text or "").strip()
    if not stripped:
        return None
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.lower().startswith("json"):
            stripped = stripped[4:]

    for opener, closer in (("{", "}"), ("[", "]")):
        start = stripped.find(opener)
        if start == -1:
            continue
        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(stripped)):
            ch = stripped[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(stripped[start : i + 1])
                    except json.JSONDecodeError:
                        return None
        return None
    return None


async def ainvoke_json(
    llm: Any,
    *,
    system: str,
    user: str,
    schema: type[BaseModel] | None = None,
) -> Any:
    """Invoke the LLM and return parsed JSON, or ``None`` when unusable.

    When ``schema`` is given the result is schema-validated on BOTH paths:
    the native path by the provider + Pydantic, the fallback path by
    ``schema.model_validate`` — so callers get a conforming dict or ``None``.
    """
    if llm is None:
        return None

    messages = [SystemMessage(content=system), HumanMessage(content=user)]

    if schema is not None:
        try:
            structured = llm.with_structured_output(schema)
            result = await structured.ainvoke(messages)
            if isinstance(result, BaseModel):
                return result.model_dump()
            if result is not None:
                logger.warning("structured output returned non-schema payload; using prompt JSON")
            else:
                logger.warning("structured output returned None; using prompt JSON")
        except Exception as e:  # noqa: BLE001 - degrade by design
            logger.warning(
                f"native structured output unavailable, using prompt JSON: {type(e).__name__}: {e}"
            )

    try:
        response = await llm.ainvoke(messages)
    except Exception as e:  # noqa: BLE001 - degrade by design
        # Bare TimeoutError's str() is "" — always name the class or the
        # production log shows an "empty message exception" with no cause.
        logger.warning(f"LLM invocation failed: {type(e).__name__}: {e}")
        return None

    content = getattr(response, "content", "")
    if isinstance(content, list | tuple):
        content = "".join(str(part) for part in content)
    parsed = extract_json(str(content or ""))
    if parsed is None:
        logger.warning("LLM response contained no parsable JSON")
        return None

    if schema is not None:
        try:
            return schema.model_validate(parsed).model_dump()
        except ValidationError as e:
            logger.warning(f"LLM JSON failed schema validation: {e}")
            return None
    return parsed
