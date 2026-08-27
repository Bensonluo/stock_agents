"""Specification tests for the V2 domain contracts (Phase 0)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.domain.schemas import (
    DataQuality,
    IssueSeverity,
    MetricEvidence,
    MetricQuality,
    QualityGateVerdict,
    QualityIssue,
    ReportV2,
    build_metric_id,
    parse_metric_id,
)

AS_OF = datetime(2026, 8, 26, 20, 0, tzinfo=UTC)


def _evidence(**overrides) -> dict:
    payload = {
        "metric_id": "AAPL.technical.sma_weekly_20.2026-08-26",
        "name": "sma_weekly_20",
        "value": 215.37,
        "unit": "USD",
        "as_of": AS_OF,
        "source": "yfinance",
        "formula": "mean(adjusted_weekly_close, 20)",
        "params": {"window": 20, "frequency": "1wk"},
        "sample_count": 20,
        "quality": MetricQuality.VERIFIED,
    }
    payload.update(overrides)
    return payload


class TestMetricId:
    def test_build_and_parse_round_trip(self) -> None:
        metric_id = build_metric_id("AAPL", "technical", "sma_weekly_20", AS_OF)

        assert metric_id == "AAPL.technical.sma_weekly_20.2026-08-26"
        symbol, domain, name, as_of_date = parse_metric_id(metric_id)
        assert (symbol, domain, name) == ("AAPL", "technical", "sma_weekly_20")
        assert as_of_date == date(2026, 8, 26)

    def test_symbol_may_contain_dots(self) -> None:
        symbol, _, _, _ = parse_metric_id("BRK.B.fundamental.roe.2026-08-26")

        assert symbol == "BRK.B"

    def test_date_object_also_accepted_for_build(self) -> None:
        assert build_metric_id("AAPL", "risk", "beta", date(2026, 8, 26)) == (
            "AAPL.risk.beta.2026-08-26"
        )

    @pytest.mark.parametrize(
        "bad_id",
        [
            "sma_weekly_20",  # too few segments
            "AAPL.technical.sma_weekly_20",  # missing date
            "AAPL.technical.sma_weekly_20.2026/08/26",  # wrong date format
            "AAPL..sma_weekly_20.2026-08-26",  # empty domain
        ],
    )
    def test_rejects_non_canonical_ids(self, bad_id: str) -> None:
        with pytest.raises(ValueError):
            parse_metric_id(bad_id)


class TestMetricEvidence:
    def test_accepts_contract_example(self) -> None:
        evidence = MetricEvidence(**_evidence())

        assert evidence.value == pytest.approx(215.37)
        assert evidence.symbol == "AAPL"
        assert evidence.domain == "technical"
        assert evidence.as_of_date == date(2026, 8, 26)

    def test_missing_data_is_explicit_not_neutral(self) -> None:
        evidence = MetricEvidence(
            **_evidence(value=None, quality=MetricQuality.INSUFFICIENT_DATA)
        )

        assert evidence.value is None
        assert evidence.quality is MetricQuality.INSUFFICIENT_DATA

    def test_concrete_quality_requires_a_value(self) -> None:
        with pytest.raises(ValidationError, match="requires a concrete value"):
            MetricEvidence(**_evidence(value=None))

    def test_insufficient_data_must_not_carry_a_value(self) -> None:
        with pytest.raises(ValidationError, match="must not carry a value"):
            MetricEvidence(**_evidence(quality=MetricQuality.INSUFFICIENT_DATA))

    def test_metric_id_must_match_canonical_format(self) -> None:
        with pytest.raises(ValidationError):
            MetricEvidence(**_evidence(metric_id="not-a-valid-id"))

    def test_naive_as_of_is_assumed_utc(self) -> None:
        evidence = MetricEvidence(**_evidence(as_of=datetime(2026, 8, 26, 20, 0)))

        assert evidence.as_of.tzinfo is UTC

    def test_round_trip_serialization(self) -> None:
        evidence = MetricEvidence(**_evidence())

        restored = MetricEvidence.model_validate(evidence.model_dump(mode="json"))

        assert restored == evidence


class TestDataQuality:
    def _quality(self, **overrides) -> DataQuality:
        payload = {
            "as_of": AS_OF,
            "symbols": ["AAPL"],
            "coverage": {"AAPL": 1.0},
            "issues": [],
        }
        payload.update(overrides)
        return DataQuality(**payload)

    def test_full_coverage_without_issues_passes(self) -> None:
        assert self._quality().verdict is QualityGateVerdict.PASS

    def test_critical_issue_blocks_conclusions(self) -> None:
        quality = self._quality(
            issues=[QualityIssue(code="look_ahead", severity=IssueSeverity.CRITICAL, subject="AAPL.prices")]
        )

        assert quality.verdict is QualityGateVerdict.INSUFFICIENT

    def test_low_coverage_blocks_conclusions(self) -> None:
        quality = self._quality(coverage={"AAPL": 0.4})

        assert quality.verdict is QualityGateVerdict.INSUFFICIENT

    def test_uncovered_symbol_counts_as_zero(self) -> None:
        quality = self._quality(symbols=["AAPL", "MSFT"], coverage={"AAPL": 1.0})

        assert quality.coverage_for("MSFT") == 0.0
        assert quality.verdict is QualityGateVerdict.INSUFFICIENT

    def test_partial_coverage_degrades(self) -> None:
        quality = self._quality(coverage={"AAPL": 0.7})

        assert quality.verdict is QualityGateVerdict.DEGRADED

    def test_warning_issue_degrades(self) -> None:
        quality = self._quality(
            issues=[
                QualityIssue(code="stale_source", severity=IssueSeverity.WARNING, subject="news")
            ]
        )

        assert quality.verdict is QualityGateVerdict.DEGRADED

    def test_coverage_must_be_a_ratio(self) -> None:
        with pytest.raises(ValidationError, match="within \\[0, 1\\]"):
            self._quality(coverage={"AAPL": 1.5})


class TestReportV2:
    def test_adapts_legacy_report_dict(self) -> None:
        legacy = {
            "title": "Investment Research Report: AAPL",
            "generated_at": "2026-08-27T10:00:00+00:00",
            "executive_summary": {"headline": "stable"},
            "sections": {
                "overview": {"symbols_analyzed": ["AAPL"]},
                "technical_analysis": {"trend": "bullish"},
            },
            "metadata": {"symbols": ["AAPL"], "query": "analyze AAPL"},
        }

        report = ReportV2.from_legacy_report(legacy, horizon="medium", benchmark="^GSPC")

        assert report.schema_version == "2.0"
        assert report.symbols == ["AAPL"]
        assert report.query == "analyze AAPL"
        assert report.horizon == "medium"
        assert report.benchmark == "^GSPC"
        assert report.sections["technical_analysis"] == {"trend": "bullish"}
        assert report.as_of == report.generated_at  # legacy cutoff falls back

    def test_extracts_symbols_from_overview_when_metadata_missing(self) -> None:
        legacy = {"sections": {"overview": {"symbols_analyzed": ["MSFT", "NVDA"]}}}

        report = ReportV2.from_legacy_report(legacy)

        assert report.symbols == ["MSFT", "NVDA"]

    def test_carries_evidence_and_quality(self) -> None:
        evidence = MetricEvidence(**_evidence())
        quality = DataQuality(as_of=AS_OF, symbols=["AAPL"], coverage={"AAPL": 1.0})

        report = ReportV2.from_legacy_report(
            {"metadata": {"symbols": ["AAPL"], "query": ""}},
            evidence=[evidence],
            data_quality=quality,
        )

        assert report.evidence == [evidence]
        assert report.data_quality is quality

    def test_round_trip_serialization_keeps_nested_contracts(self) -> None:
        report = ReportV2.from_legacy_report(
            {"metadata": {"symbols": ["AAPL"], "query": ""}},
            evidence=[MetricEvidence(**_evidence())],
            data_quality=DataQuality(as_of=AS_OF, symbols=["AAPL"], coverage={"AAPL": 0.85}),
        )

        restored = ReportV2.model_validate(report.model_dump(mode="json"))

        assert restored == report
        assert restored.evidence[0].metric_id == "AAPL.technical.sma_weekly_20.2026-08-26"
        assert restored.data_quality.verdict is QualityGateVerdict.DEGRADED
