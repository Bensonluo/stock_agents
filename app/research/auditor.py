"""Evidence Auditor (V2 plan §6).

Audits analysis packets for stale data, missing data and cross-section
conflicts BEFORE any decision is taken. The auditor never votes on
direction — it only certifies what the evidence can and cannot support.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

# Market data older than this many days is flagged stale.
STALE_AFTER_DAYS = 7


def audit_packets(
    data: dict[str, Any], *, today: date | None = None
) -> dict[str, Any]:
    """Audit all symbol packets; returns findings and a gate verdict.

    Verdict semantics:
    - ``blocked``: findings exist that must stop conclusions (stale prices,
      critical conflicts).
    - ``warnings``: soft findings; conclusions allowed but must disclose.
    - ``pass``: nothing found.
    """
    today = today or date.today()
    stale: list[dict[str, str]] = []
    insufficient: list[dict[str, str]] = []
    conflicts: list[dict[str, str]] = []

    market = data.get("market_data") or {}
    for symbol, mkt in market.items():
        as_of = mkt.get("as_of") if isinstance(mkt, dict) else None
        age = _age_days(as_of, today)
        if age is not None and age > STALE_AFTER_DAYS:
            stale.append(
                {
                    "symbol": symbol,
                    "subject": "market_data.as_of",
                    "detail": f"Data is {age} days old (as_of {as_of}).",
                }
            )

    technical = data.get("technical_analysis") or {}
    fundamental = data.get("fundamental_analysis") or {}
    risk = data.get("risk_assessment") or {}
    sentiment = _sentiment_flat(data)

    for symbol in market:
        _insufficient_findings(
            symbol, technical.get(symbol), fundamental.get(symbol), risk.get(symbol), insufficient
        )
        _conflict_findings(symbol, technical.get(symbol), fundamental.get(symbol), sentiment.get(symbol), conflicts)

    has_blocking = bool(stale) or any(c["severity"] == "critical" for c in conflicts)
    verdict = "blocked" if has_blocking else ("warnings" if (insufficient or conflicts) else "pass")

    return {
        "verdict": verdict,
        "stale": stale,
        "insufficient": insufficient,
        "conflicts": conflicts,
        "audited_at": datetime.now().isoformat(),
    }


def _insufficient_findings(
    symbol: str,
    technical: dict | None,
    fundamental: dict | None,
    risk: dict | None,
    out: list,
) -> None:
    checks = (
        ("technical_analysis", (technical or {}).get("status")),
        ("fundamental_analysis.quality", ((fundamental or {}).get("quality") or {}).get("status")),
        (
            "fundamental_analysis.valuation_scenarios",
            ((fundamental or {}).get("valuation_scenarios") or {}).get("status"),
        ),
        ("risk_assessment", (risk or {}).get("risk_level") if risk else None),
    )
    for subject, status in checks:
        if status in ("insufficient_data", "error"):
            out.append({"symbol": symbol, "subject": subject, "detail": f"status={status}"})


def _conflict_findings(
    symbol: str,
    technical: dict | None,
    fundamental: dict | None,
    sentiment: dict | None,
    out: list,
) -> None:
    quality = (fundamental or {}).get("quality") or {}
    critical_flags = [
        flag for flag in quality.get("red_flags") or [] if flag.get("severity") == "critical"
    ]
    tech_score = ((technical or {}).get("sentiment") or {}).get("score", 0) or 0
    news_score = (sentiment or {}).get("score", 0) or 0

    if critical_flags and (tech_score >= 20 or news_score >= 30):
        out.append(
            {
                "symbol": symbol,
                "severity": "critical",
                "subject": "fundamental_analysis.quality vs sentiment",
                "detail": "Critical fundamental red flags coexist with bullish momentum/news; conclusions must not ignore the flags.",
            }
        )
    elif quality.get("red_flags") and tech_score >= 40:
        out.append(
            {
                "symbol": symbol,
                "severity": "warning",
                "subject": "fundamental_analysis.quality vs technical_analysis",
                "detail": "Fundamental red flags coexist with strong technical momentum.",
            }
        )


def _sentiment_flat(data: dict[str, Any]) -> dict[str, Any]:
    sentiment = data.get("sentiment_analysis") or {}
    if "sentiment_by_symbol" in sentiment:
        return sentiment.get("sentiment_by_symbol") or {}
    return sentiment


def _age_days(as_of: Any, today: date) -> int | None:
    if isinstance(as_of, str) and as_of:
        try:
            return (today - date.fromisoformat(as_of[:10])).days
        except ValueError:
            return None
    if isinstance(as_of, datetime):
        return (today - as_of.date()).days
    if isinstance(as_of, date):
        return (today - as_of).days
    return None
