"""Evidence-constrained LLM narration over the deterministic synthesis.

The debate, audit and committee results are computed deterministically; the
LLM may only NARRATE them. Hard rules enforced by the prompt and by the
degradation policy:

- the model may not introduce any number or fact that is not in the packet;
- every narrative must reference the provided evidence;
- the PM comment must respect the committee verdict — it cannot suggest a
  direction the committee limited or vetoed;
- any failure (missing LLM, timeout, unparsable output) degrades silently to
  the deterministic synthesis.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.config import get_settings
from app.utils.llm_json import ainvoke_json
from app.utils.logging import get_logger

logger = get_logger(__name__)

_SYSTEM_PROMPT = (
    "你是股票研究报告的叙述员。你会收到每个标的的确定性多空论点、证据审计结果和风险委员会裁决。"
    "你的任务是把它们写成简明的叙述,规则如下:"
    "1) 严禁引入列表之外的新数字或新事实;2) 每段叙述必须至少引用一条给定的论点及其证据来源;"
    "3) pm_comment 必须尊重委员会裁决与条件,不得建议超出裁决的方向;"
    '4) 只输出 JSON,形如 {"symbols": {"<symbol>": {"bull_narrative": str, '
    '"bear_narrative": str, "pm_comment": str}}},不要输出其他文字。'
)


async def narrate_synthesis(
    synthesis: dict[str, Any],
    *,
    llm: Any,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Attach ``narrative`` per symbol; returns synthesis unchanged on failure.

    The budget defaults to ``settings.narration_timeout_seconds``. The old
    hardcoded 20s sat below every measured production call (33.6s on a thin
    single-symbol payload, 2026-09-25), so narration degraded on every run —
    while logging an empty-message exception, because ``str(TimeoutError())``
    is the empty string.
    """
    if llm is None or not synthesis.get("per_symbol"):
        return synthesis

    budget = get_settings().narration_timeout_seconds if timeout is None else timeout
    try:
        narratives = await asyncio.wait_for(_request_narratives(synthesis, llm), timeout=budget)
    except (TimeoutError, Exception) as e:  # noqa: BLE001 - degrade by design
        logger.warning(
            f"LLM narration unavailable after {budget}s, using deterministic synthesis: "
            f"{type(e).__name__}: {e}"
        )
        return synthesis

    per_symbol = synthesis["per_symbol"]
    for symbol, entry in per_symbol.items():
        narrative = narratives.get(symbol)
        if isinstance(narrative, dict):
            entry["narrative"] = {
                key: str(value)[:1200]
                for key, value in narrative.items()
                if isinstance(value, str) and value.strip()
            }
    return synthesis


async def _request_narratives(synthesis: dict[str, Any], llm: Any) -> dict[str, Any]:
    """Ask the LLM once for all symbols; returns {symbol: {...}} or {}."""
    user_payload = json.dumps(
        {
            "audit_verdict": (synthesis.get("audit") or {}).get("verdict"),
            "symbols": synthesis["per_symbol"],
        },
        ensure_ascii=False,
        default=str,
    )
    parsed = await ainvoke_json(llm, system=_SYSTEM_PROMPT, user=user_payload)
    return _parse_narratives(parsed, set(synthesis["per_symbol"]))


def _parse_narratives(parsed: Any, known_symbols: set[str]) -> dict[str, Any]:
    """Validate the parsed payload; anything unparseable yields {} (degradation)."""
    symbols = parsed.get("symbols") if isinstance(parsed, dict) else None
    if not isinstance(symbols, dict):
        return {}
    return {
        symbol: value
        for symbol, value in symbols.items()
        if symbol in known_symbols and isinstance(value, dict)
    }
