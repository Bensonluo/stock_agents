"""Research synthesis (V2 plan §4): debate -> audit -> committee.

Runs the deterministic research stages in the order the methodology requires:
the auditor gates first, the committee reviews only audited packets, and the
debate provides the bull/bear framing that the final decision must answer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.research.auditor import audit_packets
from app.research.committee import committee_review
from app.research.debate import bull_bear_debate


def synthesize(data: dict[str, Any]) -> dict[str, Any]:
    """Full synthesis over pipeline-state or ReAct-shaped analysis data."""
    symbols = list(data.get("symbols") or []) or list((data.get("market_data") or {}).keys())

    risk = data.get("risk_assessment") or {}
    if "risk_by_symbol" in risk:  # pipeline shape
        risk = risk.get("risk_by_symbol") or {}
    sentiment = data.get("sentiment_analysis") or {}
    if "sentiment_by_symbol" in sentiment:
        sentiment = sentiment.get("sentiment_by_symbol") or {}

    audit = audit_packets(data)

    per_symbol: dict[str, Any] = {}
    for symbol in symbols:
        packet = {
            "technical_analysis": (data.get("technical_analysis") or {}).get(symbol) or {},
            "fundamental_analysis": (data.get("fundamental_analysis") or {}).get(symbol) or {},
            "sentiment_analysis": sentiment.get(symbol) or {},
            "risk_assessment": risk.get(symbol) or {},
        }
        debate = bull_bear_debate(symbol, packet)
        committee = committee_review(
            symbol,
            risk=packet["risk_assessment"] or None,
            quality=(packet["fundamental_analysis"].get("quality") or {}) or None,
            audit_verdict=audit["verdict"],
        )
        per_symbol[symbol] = {
            "debate": debate,
            "committee": committee,
        }

    return {
        "as_of": datetime.now().isoformat(),
        "audit": audit,
        "per_symbol": per_symbol,
    }
