"""ReportV2 contract: the versioned report object the API returns.

V2 plan §2.1: the active output contract between backend and frontend is a
versioned ``ReportV2`` object; Markdown is produced by a separate renderer, and
legacy dict-shaped reports are bridged via :meth:`ReportV2.from_legacy_report`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.schemas.data_quality import DataQuality
from app.domain.schemas.metric_evidence import MetricEvidence

REPORT_SCHEMA_VERSION = "2.0"

_CORE_SECTIONS = (
    "overview",
    "technical_analysis",
    "fundamental_analysis",
    "sentiment_analysis",
    "risk_analysis",
    "recommendations",
)


class ReportV2(BaseModel):
    """Versioned analysis report with evidence and quality attached.

    Phase 0 defines the contract; later phases make every displayed number
    resolvable to a :class:`MetricEvidence` entry and populate
    :class:`DataQuality` from the quality gate.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = REPORT_SCHEMA_VERSION
    title: str = Field(default="Investment Research Report")
    query: str = Field(default="", description="User question this report answers")
    symbols: list[str] = Field(default_factory=list, description="Symbols analyzed")
    as_of: datetime = Field(
        description="Data cutoff the whole report respects; legacy reports fall back to generated_at"
    )
    generated_at: datetime = Field(description="When the report was produced")
    horizon: str | None = Field(
        default=None,
        description="Investment horizon declared before analysis (e.g. 'short', 'medium', 'long')",
    )
    benchmark: str | None = Field(
        default=None, description="Benchmark used for relative statements"
    )
    executive_summary: str | dict[str, Any] = Field(
        default="", description="Summary; may stay structured until Phase 2"
    )
    sections: dict[str, Any] = Field(
        default_factory=dict,
        description=f"Analysis sections; Phase 0 keeps the legacy keys {_CORE_SECTIONS}",
    )
    evidence: list[MetricEvidence] = Field(
        default_factory=list, description="Every number cited in sections should resolve here"
    )
    data_quality: DataQuality | None = Field(
        default=None, description="Quality-gate summary; None until the gate is wired in"
    )

    @field_validator("as_of", "generated_at")
    @classmethod
    def _naive_datetime_is_utc(cls, value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    @classmethod
    def from_legacy_report(
        cls,
        report: dict[str, Any],
        *,
        horizon: str | None = None,
        benchmark: str | None = None,
        evidence: list[MetricEvidence] | None = None,
        data_quality: DataQuality | None = None,
    ) -> ReportV2:
        """Adopt the current pipeline's dict report into the versioned contract.

        Legacy reports carry no explicit ``as_of``; ``generated_at`` is the best
        available upper bound, so it becomes the cutoff. Callers that know the
        real snapshot cutoff should migrate to constructing ``ReportV2``
        directly.
        """
        metadata = report.get("metadata") or {}
        sections = report.get("sections") or {}

        generated_at = _parse_or_now(report.get("generated_at"))

        symbols = list(metadata.get("symbols") or [])
        if not symbols:
            symbols = list(
                (sections.get("overview") or {}).get("symbols_analyzed")
                or report.get("symbols")
                or []
            )

        return cls(
            title=report.get("title") or "Investment Research Report",
            query=metadata.get("query") or "",
            symbols=symbols,
            as_of=generated_at,
            generated_at=generated_at,
            horizon=horizon,
            benchmark=benchmark,
            executive_summary=report.get("executive_summary") or "",
            sections=sections,
            evidence=evidence or [],
            data_quality=data_quality,
        )


def _parse_or_now(value: Any) -> datetime:
    """Parse an ISO timestamp or fall back to the current UTC time."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now(UTC)
