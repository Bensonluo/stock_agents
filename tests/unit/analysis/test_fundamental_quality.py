"""Specification tests for the fundamental quality engine."""

from __future__ import annotations

from datetime import UTC, datetime

from app.analysis.fundamental import financial_quality

AS_OF = datetime(2026, 8, 26, tzinfo=UTC)


def _statement(row: str, values: list[float]) -> dict:
    """Statement block in the data-agent shape; yfinance lists run newest first."""
    dates = [f"{2025 + i}-12-31" for i in range(len(values))]
    return {"dates": dates, "data": {row: values}}


def _financial(
    *,
    revenue: list[float] | None = None,
    gross: list[float] | None = None,
    net_income: list[float] | None = None,
    cfo: list[float] | None = None,
    capex: list[float] | None = None,
    equity: list[float] | None = None,
) -> dict:
    financial: dict = {}
    income_rows = {}
    if revenue is not None:
        income_rows["Total Revenue"] = revenue
    if gross is not None:
        income_rows["Gross Profit"] = gross
    if net_income is not None:
        income_rows["Net Income"] = net_income
    if income_rows:
        financial["income_statement"] = {
            "dates": [f"{2025 + i}-12-31" for i in range(len(next(iter(income_rows.values()))))],
            "data": income_rows,
        }
    cash_rows = {}
    if cfo is not None:
        cash_rows["Operating Cash Flow"] = cfo
    if capex is not None:
        cash_rows["Capital Expenditure"] = capex
    if cash_rows:
        financial["cash_flow"] = {
            "dates": [f"{2025 + i}-12-31" for i in range(len(next(iter(cash_rows.values()))))],
            "data": cash_rows,
        }
    if equity is not None:
        financial["balance_sheet"] = {
            "dates": [f"{2025 + i}-12-31" for i in range(len(equity))],
            "data": {"Stockholders Equity": equity},
        }
    return financial


class TestFinancialQuality:
    def test_healthy_company_has_no_red_flags(self) -> None:
        result = financial_quality(
            _financial(
                revenue=[80.0, 100.0, 120.0],
                gross=[32.0, 42.0, 54.0],
                net_income=[8.0, 12.0, 16.0],
                cfo=[14.0, 18.0, 22.0],
                capex=[-4.0, -5.0, -6.0],
                equity=[50.0, 60.0, 70.0],
            ),
            symbol="GOOD",
            as_of=AS_OF,
        )

        assert result["status"] == "available"
        assert result["revenue_trend"]["yoy_growth"][-1]["growth"] == 0.2
        assert result["cash_quality"]["cfo_to_net_income"] == 22.0 / 16.0
        assert result["cash_quality"]["fcf_latest"] == 16.0
        assert result["red_flags"] == []

    def test_negative_cfo_with_positive_income_is_critical(self) -> None:
        result = financial_quality(
            _financial(revenue=[100.0, 110.0], net_income=[10.0, 12.0], cfo=[5.0, -3.0]),
            symbol="FAKE",
            as_of=AS_OF,
        )

        codes = {flag["code"]: flag["severity"] for flag in result["red_flags"]}
        assert codes.get("negative_cfo_positive_ni") == "critical"
        assert result["quality_note"] is not None

    def test_negative_equity_is_critical(self) -> None:
        result = financial_quality(
            _financial(equity=[100.0, -20.0]),
            symbol="DEBT",
            as_of=AS_OF,
        )

        codes = {flag["code"] for flag in result["red_flags"]}
        assert "negative_equity" in codes

    def test_revenue_decline_flags_warning(self) -> None:
        result = financial_quality(
            _financial(revenue=[100.0, 120.0, 90.0]),
            symbol="CYCLE",
            as_of=AS_OF,
        )

        codes = {flag["code"] for flag in result["red_flags"]}
        assert "revenue_decline" in codes

    def test_margin_erosion_flagged_over_threshold(self) -> None:
        result = financial_quality(
            _financial(revenue=[100.0, 100.0], gross=[40.0, 30.0]),
            symbol="SQUEEZED",
            as_of=AS_OF,
        )

        margin = result["margin_trend"]
        assert margin["change_pp"] == -10.0
        assert any(flag["code"] == "margin_erosion" for flag in result["red_flags"])

    def test_missing_statements_are_insufficient_not_zero(self) -> None:
        result = financial_quality({}, symbol="EMPTY", as_of=AS_OF)

        assert result["status"] == "insufficient_data"
        assert result["revenue_trend"] is None
        assert result["red_flags"] == []

    def test_series_ordering_oldest_to_newest(self) -> None:
        # yfinance emits statement columns newest first; the engine must sort.
        financial = {
            "income_statement": {
                "dates": ["2026-12-31", "2025-12-31"],
                "data": {"Total Revenue": [120.0, 100.0]},
            }
        }

        result = financial_quality(financial, symbol="ORDER", as_of=AS_OF)

        trend = result["revenue_trend"]
        assert trend["values"] == [100.0, 120.0]
        assert trend["yoy_growth"][-1]["growth"] == 0.2

    def test_evidence_is_fundamental_domain_json(self) -> None:
        result = financial_quality(
            _financial(revenue=[80.0, 100.0, 120.0], cfo=[20.0, 24.0], capex=[-4.0, -5.0]),
            symbol="GOOD",
            as_of=AS_OF,
        )

        evidence = result["evidence"]
        assert evidence, "expected evidence records"
        assert all(isinstance(item, dict) for item in evidence)
        assert all(".fundamental." in item["metric_id"] for item in evidence)
        names = {item["name"] for item in evidence}
        assert "revenue_cagr" in names
        assert "fcf_latest" in names


class TestCompactQualityView:
    def test_unavailable_and_insufficient(self) -> None:
        from app.analysis.fundamental import compact_quality_view

        assert compact_quality_view(None) == {"status": "unavailable"}
        assert compact_quality_view({"status": "insufficient_data"}) == {
            "status": "insufficient_data"
        }

    def test_available_view_carries_verdict_and_flags(self) -> None:
        from app.analysis.fundamental import compact_quality_view

        full = financial_quality(
            _financial(revenue=[100.0, 110.0], net_income=[10.0, 12.0], cfo=[5.0, -3.0]),
            symbol="FAKE",
            as_of=AS_OF,
        )

        view = compact_quality_view(full)

        assert view["status"] == "available"
        assert any(flag["code"] == "negative_cfo_positive_ni" for flag in view["red_flags"])
        assert view["cfo_to_net_income"] == full["cash_quality"]["cfo_to_net_income"]
