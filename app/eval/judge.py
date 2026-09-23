"""Optional LLM-as-judge for report quality (eval harness companion).

Gated by EVAL_LLM_JUDGE (default off): deterministic rubric grading stays the
regression gate; the judge adds open-ended scores when a key and explicit
opt-in are available. Degrades to None by design.
"""

from pydantic import BaseModel, Field

from app.config import settings
from app.utils.llm_json import ainvoke_json
from app.utils.logging import get_logger

logger = get_logger(__name__)

ZHIPU_API_BASE = "https://open.bigmodel.cn/api/coding/paas/v4/"

_JUDGE_SYSTEM = """You are a strict evaluator of equity research reports.
Score the report on four dimensions, each 0-10:
- completeness: are all standard sections present and substantive?
- groundedness: are claims tied to the provided data excerpts?
- actionability: could a reader act on the recommendation?
- risk_awareness: are risks, drawdowns and failure modes surfaced?
Be conservative; reserve 9-10 for genuinely excellent work."""


class JudgeVerdict(BaseModel):
    """LLM judge output contract."""

    completeness: int = Field(ge=0, le=10)
    groundedness: int = Field(ge=0, le=10)
    actionability: int = Field(ge=0, le=10)
    risk_awareness: int = Field(ge=0, le=10)
    overall: int = Field(ge=0, le=10)
    rationale: str = ""


async def judge_report(report_text: str) -> dict | None:
    """Grade a rendered report with the LLM judge.

    Returns:
        JudgeVerdict dump, or None when the judge is disabled/unavailable.
    """
    if not settings.eval_llm_judge:
        return None

    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model=settings.primary_llm_model,
        temperature=0.0,
        max_tokens=600,
        timeout=settings.llm_timeout,
        openai_api_key=settings.zhipuai_api_key,
        openai_api_base=ZHIPU_API_BASE,
    )
    if not settings.zhipuai_api_key:
        logger.warning("EVAL_LLM_JUDGE enabled but ZHIPUAI_API_KEY is not set; skipping judge")
        return None

    user = f"Report to evaluate:\n\n{report_text[:12000]}"
    verdict = await ainvoke_json(llm, system=_JUDGE_SYSTEM, user=user, schema=JudgeVerdict)
    if verdict is None:
        logger.warning("LLM judge returned no parsable verdict; degrading to None")
    return verdict
