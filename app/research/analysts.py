"""Evidence-constrained analyst panel and portfolio manager (V2 plan §6).

The deterministic engines produce facts; the LLM roles here may only
INTERPRET them. Enforcement is structural, not honor-system:

- each role receives a compact packet and the exact list of evidence refs it
  may cite;
- a role's output must carry ``cites`` — refs outside the allowed set, or an
  empty citation list, cause that role's view to be dropped;
- the PM must restate the committee verdict verbatim or its conclusion is
  dropped (the PM cannot overrule the gate);
- any failure (missing LLM, timeout, unparsable JSON) degrades silently:
  the deterministic synthesis remains the source of truth.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.config import get_settings
from app.utils.llm_json import ainvoke_json
from app.utils.logging import get_logger

logger = get_logger(__name__)

_ROLES = ("technical", "fundamental", "valuation", "event")

_SYSTEM_PROMPT = (
    "你是股票研究团队。针对每个标的,你会收到确定性引擎产出的紧凑事实包与可用证据引用列表。"
    "四个角色(technical/fundamental/valuation/event)各写一段不超过 80 字的解读,"
    "组合经理(pm)给出最终结论。硬性规则:"
    "1) 严禁使用事实包之外的任何数字或事实;"
    "2) 每个角色的输出必须带 cites 字段,只允许引用提供的 ref;"
    "3) pm 必须原样填写 committee_verdict 字段,不得建议超出裁决的方向;"
    "4) 只输出 JSON:"
    '{"symbols": {"<sym>": {"technical": {"view": str, "cites": [str]}, '
    '"fundamental": {...}, "valuation": {...}, "event": {...}, '
    '"pm": {"thesis": str, "horizon": str, "conditions": [str], '
    '"invalidation": str, "committee_verdict": str}}}}'
)


async def attach_analyst_panel(
    synthesis: dict[str, Any],
    *,
    llm: Any,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Attach ``analysts`` and ``pm`` per symbol; degrade to unchanged output.

    The budget defaults to ``settings.panel_timeout_seconds``. The old
    hardcoded 25s sat below every measured production call (36.6s on a thin
    single-symbol payload, 2026-09-25), so the panel degraded on every run —
    while logging an empty-message exception, because ``str(TimeoutError())``
    is the empty string.
    """
    if llm is None or not synthesis.get("per_symbol"):
        return synthesis

    budget = get_settings().panel_timeout_seconds if timeout is None else timeout
    try:
        panel = await asyncio.wait_for(_request_panel(synthesis, llm), timeout=budget)
    except (TimeoutError, Exception) as e:  # noqa: BLE001 - degrade by design
        logger.warning(
            f"Analyst panel unavailable after {budget}s, keeping deterministic synthesis: "
            f"{type(e).__name__}: {e}"
        )
        return synthesis

    for symbol, entry in synthesis["per_symbol"].items():
        result = panel.get(symbol) or {}
        analysts = {role: result[role] for role in _ROLES if isinstance(result.get(role), dict)}
        if analysts:
            entry["analysts"] = analysts
        if isinstance(result.get("pm"), dict):
            entry["pm"] = result["pm"]
    return synthesis


async def _request_panel(synthesis: dict[str, Any], llm: Any) -> dict[str, dict[str, Any]]:
    """One LLM call for all symbols; returns validated {symbol: {...}}."""
    payloads: dict[str, Any] = {}
    for symbol, entry in synthesis["per_symbol"].items():
        debate = entry.get("debate") or {}
        refs = sorted(
            {
                point["evidence_ref"]
                for point in (debate.get("bull_points") + debate.get("bear_points", []))
            }
        )
        payloads[symbol] = {
            "facts": {
                "thesis": debate.get("thesis"),
                "strongest_counter": debate.get("strongest_counter"),
                "invalidation": debate.get("invalidation"),
                "bull_points": debate.get("bull_points", []),
                "bear_points": debate.get("bear_points", []),
                "audit_verdict": (synthesis.get("audit") or {}).get("verdict"),
                "committee": entry.get("committee"),
            },
            "allowed_refs": refs or ["deterministic_synthesis"],
        }

    parsed = await ainvoke_json(
        llm,
        system=_SYSTEM_PROMPT,
        user=json.dumps(payloads, ensure_ascii=False, default=str),
    )
    return _validate_panel(parsed, payloads)


def _validate_panel(parsed: Any, payloads: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Structurally validate the panel payload; bad parts are dropped."""
    if not isinstance(parsed, dict) or not isinstance(parsed.get("symbols"), dict):
        return {}

    validated: dict[str, dict[str, Any]] = {}
    for symbol, allowed in payloads.items():
        allowed_refs = set(allowed["allowed_refs"])
        committee_verdict = ((allowed["facts"].get("committee") or {}).get("verdict")) or ""
        block: dict[str, Any] = {}

        for role in _ROLES:
            view = parsed["symbols"].get(symbol, {}).get(role)
            cleaned = _clean_cited_view(view, allowed_refs)
            if cleaned is not None:
                block[role] = cleaned

        pm = parsed["symbols"].get(symbol, {}).get("pm")
        if isinstance(pm, dict) and isinstance(pm.get("thesis"), str) and pm["thesis"].strip():
            if str(pm.get("committee_verdict", "")).strip() == committee_verdict:
                block["pm"] = {
                    "thesis": pm["thesis"][:800],
                    "horizon": str(pm.get("horizon", ""))[:80],
                    "conditions": [
                        str(c)[:200] for c in (pm.get("conditions") or []) if str(c).strip()
                    ][:6],
                    "invalidation": str(pm.get("invalidation", ""))[:400],
                    "committee_verdict": committee_verdict,
                }
            else:
                logger.warning(
                    f"PM conclusion for {symbol} dropped: committee verdict not restated"
                )

        if block:
            validated[symbol] = block
    return validated


def _clean_cited_view(view: Any, allowed_refs: set[str]) -> dict[str, Any] | None:
    """Keep a role view only when its text exists and citations are valid."""
    if not isinstance(view, dict):
        return None
    text = view.get("view")
    if not isinstance(text, str) or not text.strip():
        return None
    cites = [ref for ref in (view.get("cites") or []) if ref in allowed_refs]
    if not cites:
        return None
    return {"view": text.strip()[:600], "cites": cites}
