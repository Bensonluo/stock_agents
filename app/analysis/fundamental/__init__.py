"""Fundamental quality engine (V2 plan §5.1)."""

from app.analysis.fundamental.engine import compact_quality_view, financial_quality
from app.analysis.fundamental.trends import quarterly_statement_trends, trend_annotation

__all__ = [
    "compact_quality_view",
    "financial_quality",
    "quarterly_statement_trends",
    "trend_annotation",
]
