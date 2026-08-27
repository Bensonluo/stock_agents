"""MetricEvidence contract: every number cited in a V2 report is traceable.

Phase 0 of the V2 upgrade (docs/stock-analysis-v2-upgrade-plan.md §4): computed
values must travel with unit, as-of cutoff, source, formula and a quality flag
instead of propagating as bare floats between agents.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Qualities that assert a real observation; INSUFFICIENT_DATA asserts absence.
_CONCRETE_QUALITIES = frozenset(
    {"verified", "estimated", "stale", "conflict"},
)


def parse_metric_id(metric_id: str) -> tuple[str, str, str, date]:
    """Split ``symbol.domain.name.YYYY-MM-DD`` into its parts.

    Symbols may themselves contain dots (e.g. ``BRK.B``), so parsing anchors on
    the trailing date, then name and domain; everything before is the symbol.

    Raises:
        ValueError: if the id is not in the canonical format.
    """
    parts = metric_id.split(".")
    if len(parts) < 4:
        raise ValueError(
            f"metric_id must be 'symbol.domain.name.YYYY-MM-DD', got {metric_id!r}"
        )
    *symbol_parts, domain, name, as_of_date = parts
    if not all(symbol_parts) or not domain or not name:
        raise ValueError(f"metric_id has empty segments: {metric_id!r}")
    try:
        parsed_date = date.fromisoformat(as_of_date)
    except ValueError as exc:
        raise ValueError(
            f"metric_id must end with a YYYY-MM-DD date, got {metric_id!r}"
        ) from exc
    return ".".join(symbol_parts), domain, name, parsed_date


def build_metric_id(symbol: str, domain: str, name: str, as_of: datetime | date) -> str:
    """Build the canonical metric id ``symbol.domain.name.YYYY-MM-DD``."""
    if not symbol or not domain or not name:
        raise ValueError("symbol, domain and name must be non-empty")
    if any("." in part for part in (domain, name)):
        raise ValueError("domain and name must not contain dots")
    return f"{symbol}.{domain}.{name}.{as_of:%Y-%m-%d}"


class MetricQuality(StrEnum):
    """Enumeration of evidence quality states."""

    VERIFIED = "verified"
    ESTIMATED = "estimated"
    STALE = "stale"
    CONFLICT = "conflict"
    INSUFFICIENT_DATA = "insufficient_data"


class MetricEvidence(BaseModel):
    """A single sourced metric observation.

    Contract (V2 plan §4): any precise number shown to users must resolve to an
    evidence record like this one; a missing observation is represented by
    ``quality=INSUFFICIENT_DATA`` with ``value=None`` — never a neutral filler
    score.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_id: str = Field(
        description="Canonical id 'symbol.domain.name.YYYY-MM-DD' (symbol may contain dots)",
        examples=["AAPL.technical.sma_weekly_20.2026-08-26"],
    )
    name: str = Field(description="Metric name, e.g. 'sma_weekly_20'")
    value: float | None = Field(
        default=None, description="Observed value; None only when quality=insufficient_data"
    )
    unit: str = Field(description="Unit of value, e.g. 'USD', 'ratio', 'percent'")
    as_of: datetime = Field(description="Data cutoff; no observation may be newer than this")
    source: str = Field(description="Provider name, e.g. 'yfinance'")
    source_ref: str | None = Field(
        default=None, description="Snapshot id or URL pinning the observation"
    )
    formula: str | None = Field(
        default=None, description="How the value was computed, e.g. 'mean(adjusted_weekly_close, 20)'"
    )
    params: dict[str, Any] = Field(
        default_factory=dict, description="Formula parameters (window, frequency, adjustment...)"
    )
    sample_count: int | None = Field(
        default=None, description="Observations used; None when unknown", ge=0
    )
    quality: MetricQuality

    @field_validator("metric_id")
    @classmethod
    def _id_must_be_canonical(cls, value: str) -> str:
        parse_metric_id(value)
        return value

    @field_validator("as_of")
    @classmethod
    def _naive_datetime_is_utc(cls, value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    @model_validator(mode="after")
    def _quality_value_consistency(self) -> MetricEvidence:
        if self.quality.value in _CONCRETE_QUALITIES and self.value is None:
            raise ValueError(f"quality={self.quality.value} requires a concrete value")
        if self.quality is MetricQuality.INSUFFICIENT_DATA and self.value is not None:
            raise ValueError("quality=insufficient_data must not carry a value")
        return self

    @property
    def symbol(self) -> str:
        """Symbol segment of the metric id."""
        return parse_metric_id(self.metric_id)[0]

    @property
    def domain(self) -> str:
        """Domain segment (technical/fundamental/...) of the metric id."""
        return parse_metric_id(self.metric_id)[1]

    @property
    def as_of_date(self) -> date:
        """Date segment of the metric id."""
        return parse_metric_id(self.metric_id)[3]
