"""Enhancement-layer timeout budgets and diagnostic logging.

Production evidence (Tencent Cloud deploy, 2026-09-25): glm-5.3-flash took
33.6s/36.6s for the narrator/panel calls on a thin single-symbol payload
while the old hardcoded budgets were 20s/25s — every production call timed
out, silently disabling both LLM enhancement layers, and the logs showed an
"empty message exception" because ``str(TimeoutError())`` is the empty
string. These tests pin the settings-driven budgets (defaults derived from
the measured latency), the degrade-on-timeout behavior, and the
exception-class-name logging that makes the next such failure diagnosable.
"""

from __future__ import annotations

import asyncio

import pytest

import app.research.analysts as analysts_mod
import app.research.narrator as narrator_mod
import app.utils.llm_json as llm_json_mod
from app.config import get_settings
from app.research import attach_analyst_panel, narrate_synthesis
from app.utils.llm_json import ainvoke_json

pytestmark = pytest.mark.asyncio


def _synthesis() -> dict:
    return {
        "audit": {"verdict": "proceed"},
        "per_symbol": {"AAPL": {"debate": {}, "committee": {}}},
    }


async def test_default_budgets_exceed_measured_latency() -> None:
    """Defaults are pinned against the measured latency — a silent revert to
    the old 20/25s budgets would disable both layers in production again.
    The sequential worst case must also stay inside the synthesis node's
    budget (timeout_per_agent)."""
    settings = get_settings()
    assert settings.narration_timeout_seconds == pytest.approx(45.0)
    assert settings.panel_timeout_seconds == pytest.approx(60.0)
    assert (
        settings.narration_timeout_seconds + settings.panel_timeout_seconds
        < settings.timeout_per_agent
    )


async def test_narrator_budget_comes_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """A settings budget tighter than the call duration degrades narration to
    the unchanged deterministic synthesis instead of raising."""
    monkeypatch.setattr(get_settings(), "narration_timeout_seconds", 0.05)

    async def _slow(synthesis, llm):
        await asyncio.sleep(0.2)
        raise AssertionError("wait_for must cancel before the call finishes")

    monkeypatch.setattr(narrator_mod, "_request_narratives", _slow)

    synthesis = _synthesis()
    result = await narrate_synthesis(synthesis, llm=object())

    assert result is synthesis  # returned unchanged — degradation
    assert "narrative" not in result["per_symbol"]["AAPL"]


async def test_narrator_timeout_log_names_the_exception_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """str(TimeoutError()) is "" — the warning must carry the class name and
    the budget (the production "empty message exception" hid the cause)."""
    monkeypatch.setattr(get_settings(), "narration_timeout_seconds", 0.05)

    async def _hang(synthesis, llm):
        await asyncio.sleep(5)

    monkeypatch.setattr(narrator_mod, "_request_narratives", _hang)

    warnings: list[str] = []
    monkeypatch.setattr(narrator_mod.logger, "warning", lambda msg: warnings.append(str(msg)))

    await narrate_synthesis(_synthesis(), llm=object())

    assert warnings, "degradation must warn"
    assert "TimeoutError" in warnings[0]
    assert "after 0.05s" in warnings[0]


async def test_panel_budget_comes_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "panel_timeout_seconds", 0.05)

    async def _slow(synthesis, llm):
        await asyncio.sleep(0.2)
        raise AssertionError("wait_for must cancel before the call finishes")

    monkeypatch.setattr(analysts_mod, "_request_panel", _slow)

    synthesis = _synthesis()
    result = await attach_analyst_panel(synthesis, llm=object())

    assert result is synthesis
    assert "analysts" not in result["per_symbol"]["AAPL"]


async def test_panel_timeout_log_names_the_exception_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "panel_timeout_seconds", 0.05)

    async def _hang(synthesis, llm):
        await asyncio.sleep(5)

    monkeypatch.setattr(analysts_mod, "_request_panel", _hang)

    warnings: list[str] = []
    monkeypatch.setattr(analysts_mod.logger, "warning", lambda msg: warnings.append(str(msg)))

    await attach_analyst_panel(_synthesis(), llm=object())

    assert warnings, "degradation must warn"
    assert "TimeoutError" in warnings[0]
    assert "after 0.05s" in warnings[0]


async def test_ainvoke_json_log_names_the_exception_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared JSON boundary logs client-side timeouts with their class —
    bare ``TimeoutError`` from the transport must not render as empty text."""

    class TimingOutLLM:
        async def ainvoke(self, messages):
            raise TimeoutError()

    warnings: list[str] = []
    monkeypatch.setattr(llm_json_mod.logger, "warning", lambda msg: warnings.append(str(msg)))

    parsed = await ainvoke_json(TimingOutLLM(), system="s", user="u")

    assert parsed is None
    assert any("TimeoutError" in w for w in warnings)
