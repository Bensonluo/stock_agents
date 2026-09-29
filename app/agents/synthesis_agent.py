"""Research synthesis agent (V2 plan §4, §6).

Runs the deterministic Bull/Bear debate, Evidence Auditor and Risk Committee
over the completed analysis packets, in that order. It writes a single
``research_synthesis`` state key; the decision and report agents downstream
must respect the auditor's gate and the committee's conditions.
"""

import asyncio
from datetime import datetime
from typing import Any

from app.agents.base import StatelessAgent
from app.orchestration.state import AgentState
from app.research import attach_analyst_panel, narrate_synthesis, synthesize
from app.utils.logging import get_logger

logger = get_logger(__name__)


class ResearchSynthesisAgent(StatelessAgent):
    """Bull/Bear debate -> Evidence audit -> Risk committee, as one node."""

    async def process(self, state: AgentState) -> dict[str, Any]:
        data = {
            "query": state.get("query", ""),
            "symbols": state.get("symbols", []),
            "market_data": state.get("market_data", {}),
            "technical_analysis": state.get("technical_analysis", {}),
            "fundamental_analysis": state.get("fundamental_analysis", {}),
            "sentiment_analysis": state.get("sentiment_analysis", {}),
            "risk_assessment": state.get("risk_assessment", {}),
        }

        synthesis = synthesize(data)
        if self.llm is not None:
            # Both enhancement layers serialize their prompts before awaiting
            # the LLM, then write disjoint per-symbol keys (narrative vs
            # analysts/pm) into this shared dict and return it, so they are
            # safe to run concurrently: worst-case wall time drops from
            # narration + panel to max(narration, panel).
            narrated, _panelled = await asyncio.gather(
                narrate_synthesis(synthesis, llm=self.llm),
                attach_analyst_panel(synthesis, llm=self.llm),
            )
            synthesis = narrated
        blocked = synthesis["audit"]["verdict"] == "blocked"
        logger.info(
            "Research synthesis complete: audit=%s, symbols=%d%s",
            synthesis["audit"]["verdict"],
            len(synthesis["per_symbol"]),
            " (BLOCKED)" if blocked else "",
        )
        return {
            "research_synthesis": synthesis,
            "timestamp": datetime.now().isoformat(),
        }
