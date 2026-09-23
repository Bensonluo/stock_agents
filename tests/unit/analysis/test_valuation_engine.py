"""Specification tests for the scenario valuation engine."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.analysis.valuation import scenario_valuation, sensitivity_table

AS_OF = datetime(2026, 8, 26, tzinfo=UTC)


def _earnings_kwargs(**overrides):
    payload = {
        "symbol": "AAPL",
        "current_price": 100.0,
        "trailing_eps": 2.0,
        "ps_ratio": None,
        "earnings_growth": None,
        "revenue_growth": None,
        "as_of": AS_OF,
        "source": "test",
    }
    payload.update(overrides)
    return payload


class TestEarningsMethod:
    def test_base_scenario_anchors_to_own_multiple(self) -> None:
        result = scenario_valuation(**_earnings_kwargs())

        method = result["methods"]["earnings_multiple"]
        assert method["status"] == "available"
        assert method["current_pe"] == pytest.approx(50.0)
        # eps 2.0, zero growth, factor 1.0 -> value = price
        assert method["scenarios"]["base"]["value"] == pytest.approx(100.0)
        # bear: eps 2.0*(1-0.05) * pe 50 * factor 0.75
        assert method["scenarios"]["bear"]["value"] == pytest.approx(71.25)
        # bull: eps 2.0*1.05 * pe 50 * factor 1.25
        assert method["scenarios"]["bull"]["value"] == pytest.approx(131.25)

    def test_growth_shifts_forward_eps(self) -> None:
        result = scenario_valuation(**_earnings_kwargs(earnings_growth=0.10))

        scenarios = result["methods"]["earnings_multiple"]["scenarios"]
        # bear growth = 0.10 - 0.05 = 0.05 -> eps 2.1 * pe 50 * 0.75
        assert scenarios["bear"]["value"] == pytest.approx(2.1 * 50 * 0.75)
        # base growth 0.10 -> eps 2.2 * pe 50
        assert scenarios["base"]["value"] == pytest.approx(110.0)

    def test_extreme_growth_is_clipped(self) -> None:
        result = scenario_valuation(**_earnings_kwargs(earnings_growth=5.0))

        assumptions = result["methods"]["earnings_multiple"]["scenarios"]["bull"]["assumptions"]
        assert assumptions["growth_used"] == 0.5

    def test_sensitivity_grid_is_three_by_three(self) -> None:
        result = scenario_valuation(**_earnings_kwargs())

        grid = result["methods"]["earnings_multiple"]["sensitivity"]["values"]
        assert set(grid) == {"bear", "base", "bull"}
        assert all(set(row) == {"bear", "base", "bull"} for row in grid.values())
        assert grid["base"]["base"] == pytest.approx(100.0)


class TestSalesMethod:
    def test_loss_making_falls_back_to_sales_multiple(self) -> None:
        result = scenario_valuation(
            **_earnings_kwargs(trailing_eps=-0.5, ps_ratio=10.0, revenue_growth=0.2)
        )

        assert "earnings_multiple" not in result["methods"]
        sales = result["methods"]["sales_multiple"]
        assert sales["scenarios"]["base"]["value"] == pytest.approx(100.0 * 1.2)
        assert result["status"] == "available"

    def test_single_method_when_other_data_missing(self) -> None:
        result = scenario_valuation(**_earnings_kwargs())  # ps_ratio absent

        assert result["status"] == "available"
        assert set(result["methods"]) == {"earnings_multiple"}


class TestEvidenceAndGuards:
    def test_no_data_is_insufficient(self) -> None:
        result = scenario_valuation(**_earnings_kwargs(current_price=None, trailing_eps=None))

        assert result["status"] == "insufficient_data"
        assert result["evidence"] == []

    def test_evidence_uses_valuation_domain(self) -> None:
        result = scenario_valuation(**_earnings_kwargs())

        ids = [item["metric_id"] for item in result["evidence"]]
        assert all(".valuation." in metric_id for metric_id in ids)
        assert "AAPL.valuation.valuation_earnings_base.2026-08-26" in ids


class TestSensitivityHelper:
    def test_sensitivity_table_grows_with_growth(self) -> None:
        table = sensitivity_table(100.0, growth=0.10)

        values = table["values"]
        assert values["bull"]["bull"] > values["base"]["base"] > values["bear"]["bear"]
        assert table["columns"].startswith("multiple factor")


class TestCompactValuationView:
    def test_unavailable_inputs(self) -> None:
        from app.analysis.valuation import compact_valuation_view

        for pack in (None, {}, {"status": "error"}):
            assert compact_valuation_view(pack) == {"status": "unavailable"}

    def test_scenarios_aggregated_across_methods(self) -> None:
        from app.analysis.valuation import compact_valuation_view

        result = scenario_valuation(**_earnings_kwargs(trailing_eps=2.0, ps_ratio=10.0))

        view = compact_valuation_view(result)

        assert view["status"] == "available"
        assert set(view["scenarios"]) == {"bear", "base", "bull"}
        assert view["scenarios"]["base"]["earnings_multiple"]["value"] == pytest.approx(100.0)
        assert view["scenarios"]["base"]["sales_multiple"]["value"] == pytest.approx(100.0)
