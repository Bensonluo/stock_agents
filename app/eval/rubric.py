"""Deterministic report-quality rubric.

Grades a generated pipeline report against structural invariants that must
hold for EVERY scenario (happy path and degraded inputs alike). Used by the
eval suite as a regression gate: any check that flips from pass to fail is a
quality regression, and the per-check breakdown shows which invariant broke
instead of one opaque assertion.
"""

import json
from dataclasses import dataclass, field
from typing import Any

REPORT_SECTIONS = (
    "overview",
    "technical_analysis",
    "fundamental_analysis",
    "sentiment_analysis",
    "risk_analysis",
    "recommendations",
    "research_synthesis",
    "evidence_index",
)

DECISION_ACTIONS = frozenset(
    {
        "strong_buy",
        "buy",
        "moderate_buy",
        "add",
        "hold",
        "reduce",
        "moderate_sell",
        "sell",
        "strong_sell",
    }
)

COMMITTEE_VERDICTS = frozenset({"approve", "limit", "veto", "watch"})


@dataclass
class EvalResult:
    """Rubric outcome: per-check results plus a 0..1 score."""

    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    @property
    def score(self) -> float:
        if not self.checks:
            return 0.0
        return sum(1 for _, ok, _ in self.checks if ok) / len(self.checks)

    @property
    def passed(self) -> bool:
        return all(ok for _, ok, _ in self.checks)

    def failures(self) -> list[str]:
        return [f"{name}: {detail}" for name, ok, detail in self.checks if not ok]

    def summary(self) -> str:
        failed = self.failures()
        head = f"score={self.score:.2f} ({len(self.checks) - len(failed)}/{len(self.checks)})"
        return head + (" FAIL -> " + "; ".join(failed) if failed else " PASS")


def grade_report(
    report: dict[str, Any] | None,
    decisions: dict[str, Any],
    symbols: list[str],
) -> EvalResult:
    """Grade a pipeline report. Every check must pass for the gate to hold.

    Args:
        report: The report_generation agent's output.
        decisions: Decisions by symbol (state["decision"]["decisions"]).
        symbols: Symbols the analysis was requested for.
    """
    result = EvalResult()

    def check(name: str, ok: bool, detail: str = "") -> None:
        result.checks.append((name, bool(ok), detail))

    if not isinstance(report, dict):
        check("report.is_dict", False, f"got {type(report).__name__}")
        return result

    check("report.title", bool(str(report.get("title") or "").strip()))
    check("report.summary", bool(str(report.get("executive_summary") or "").strip()))

    sections = report.get("sections") or {}
    missing = [key for key in REPORT_SECTIONS if key not in sections]
    check("report.sections_complete", not missing, f"missing {missing}")

    # Decisions cover every requested symbol with valid action + confidence.
    decisions = decisions or {}
    if decisions:
        covered = set(decisions) & set(symbols)
        check(
            "decision.symbol_coverage",
            covered == set(symbols),
            f"missing {sorted(set(symbols) - covered)}",
        )
        bad_actions = {
            s: d.get("action")
            for s, d in decisions.items()
            if d.get("action") not in DECISION_ACTIONS
        }
        check("decision.action_enum", not bad_actions, f"invalid {bad_actions}")
        bad_conf = {
            s: d.get("confidence")
            for s, d in decisions.items()
            if not isinstance(d.get("confidence"), int | float)
        }
        check("decision.confidence_numeric", not bad_conf, f"non-numeric {bad_conf}")
    else:
        check("decision.present", False, "no decisions block in report")

    # Evidence drawer has at least one record per symbol.
    evidence = sections.get("evidence_index") or {}
    empty_evidence = [s for s in symbols if not evidence.get(s)]
    check("evidence.per_symbol", not empty_evidence, f"empty for {empty_evidence}")

    # Committee verdicts are from the closed set.
    synthesis = sections.get("research_synthesis") or {}
    by_symbol = synthesis.get("by_symbol") or {}
    bad_verdicts = {
        s: entry.get("committee_verdict")
        for s, entry in by_symbol.items()
        if entry.get("committee_verdict") not in COMMITTEE_VERDICTS
    }
    if by_symbol:
        check("synthesis.committee_verdict_enum", not bad_verdicts, f"invalid {bad_verdicts}")

    # JSON-serializable end to end (numpy/ndarray leak detector).
    try:
        payload = json.dumps(report, ensure_ascii=False, default=str)
        check("report.json_serializable", len(payload) > 1000, "payload suspiciously small")
    except (TypeError, ValueError) as exc:
        check("report.json_serializable", False, str(exc))

    return result
