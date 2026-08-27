"""V2 data contracts (Phase 0): metric evidence, data quality, versioned report."""

from app.domain.schemas.data_quality import (
    DataQuality,
    IssueSeverity,
    QualityGateVerdict,
    QualityIssue,
)
from app.domain.schemas.metric_evidence import (
    MetricEvidence,
    MetricQuality,
    build_metric_id,
    parse_metric_id,
)
from app.domain.schemas.report_v2 import REPORT_SCHEMA_VERSION, ReportV2

__all__ = [
    "DataQuality",
    "IssueSeverity",
    "MetricEvidence",
    "MetricQuality",
    "QualityGateVerdict",
    "QualityIssue",
    "REPORT_SCHEMA_VERSION",
    "ReportV2",
    "build_metric_id",
    "parse_metric_id",
]
