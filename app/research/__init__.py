"""Research synthesis layer (V2 plan §4): debate, audit, committee."""

from app.research.auditor import audit_packets
from app.research.committee import committee_review
from app.research.debate import bull_bear_debate
from app.research.narrator import narrate_synthesis
from app.research.synthesis import synthesize

__all__ = [
    "audit_packets",
    "bull_bear_debate",
    "committee_review",
    "narrate_synthesis",
    "synthesize",
]
