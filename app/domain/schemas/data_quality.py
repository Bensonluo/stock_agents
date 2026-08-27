"""DataQuality contract: the quality gate every snapshot must pass (V2 plan §5.1).

Phase 0 defines the schema; later phases compute it in ``app/data/quality/``
from freshness, coverage, conflicts and as-of checks. The verdict implements the
hard gate from V2 plan §3.3: insufficient data must yield ``insufficient_data``,
never a neutral filler score.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

# A symbol below this coverage cannot support conclusions at all.
MIN_COVERAGE_FOR_CONCLUSIONS = 0.5
# Below full coverage (or with warnings) the report must carry explicit caveats.
FULL_COVERAGE = 0.9


class IssueSeverity(StrEnum):
    """How much an issue constrains downstream conclusions."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class QualityIssue(BaseModel):
    """A single quality finding, e.g. stale source, conflict or look-ahead."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(
        description="Machine-readable issue code",
        examples=["missing_field", "stale_source", "conflict", "look_ahead"],
    )
    severity: IssueSeverity
    subject: str = Field(description="Field, metric id or source the issue refers to")
    detail: str = Field(default="", description="Human-readable explanation")


class QualityGateVerdict(StrEnum):
    """Outcome of the data-quality gate."""

    PASS = "pass"
    DEGRADED = "degraded"
    INSUFFICIENT = "insufficient"


class DataQuality(BaseModel):
    """Per-run quality summary attached to a report.

    ``coverage`` maps each analyzed symbol to the share of required metrics that
    were actually available at ``as_of`` (0.0-1.0). Missing symbols default to
    0.0 coverage.
    """

    model_config = ConfigDict(extra="forbid")

    as_of: datetime = Field(description="Cutoff all included data respects")
    symbols: list[str] = Field(min_length=1, description="Symbols this run analyzed")
    coverage: dict[str, float] = Field(
        default_factory=dict,
        description="symbol -> share of required metrics available (0..1)",
    )
    issues: list[QualityIssue] = Field(default_factory=list)

    @field_validator("as_of")
    @classmethod
    def _naive_datetime_is_utc(cls, value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    @field_validator("coverage")
    @classmethod
    def _coverage_in_unit_interval(cls, value: dict[str, float]) -> dict[str, float]:
        for symbol, ratio in value.items():
            if not 0.0 <= ratio <= 1.0:
                raise ValueError(f"coverage for {symbol!r} must be within [0, 1], got {ratio}")
        return value

    def coverage_for(self, symbol: str) -> float:
        """Coverage of ``symbol``; 0.0 when nothing was recorded."""
        return self.coverage.get(symbol, 0.0)

    @property
    def has_critical_issues(self) -> bool:
        """Whether any recorded issue is critical."""
        return any(issue.severity is IssueSeverity.CRITICAL for issue in self.issues)

    @property
    def verdict(self) -> QualityGateVerdict:
        """Hard gate outcome for this run.

        - any critical issue, or a symbol below ``MIN_COVERAGE_FOR_CONCLUSIONS``:
          ``INSUFFICIENT`` — report observations only, no scores or conclusions;
        - any warning, or coverage below ``FULL_COVERAGE``: ``DEGRADED`` —
          conclusions allowed but must disclose the gaps;
        - otherwise: ``PASS``.
        """
        if self.has_critical_issues:
            return QualityGateVerdict.INSUFFICIENT
        if any(
            self.coverage_for(symbol) < MIN_COVERAGE_FOR_CONCLUSIONS
            for symbol in self.symbols
        ):
            return QualityGateVerdict.INSUFFICIENT
        if any(issue.severity is IssueSeverity.WARNING for issue in self.issues):
            return QualityGateVerdict.DEGRADED
        if any(self.coverage_for(symbol) < FULL_COVERAGE for symbol in self.symbols):
            return QualityGateVerdict.DEGRADED
        return QualityGateVerdict.PASS
