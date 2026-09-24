"""Risk annotation pass-through: the report is the frontend's only wire.

Iterations 42/45 added liquidity and sector-relative annotation blocks at the
assessment seam, but ``_risk`` emitted a fixed six-field card — the annotations
died one layer before the API response, so no frontend could ever render them.
These tests pin the pass-through contract: enriched blocks reach the report
JSON when present, degraded entries gain no keys, and the portfolio
correlation view (already flowing through ``portfolio_risk``) stays intact.
"""

from __future__ import annotations

from app.services.report_service import ReportService


def _risk_entry(enriched: bool) -> dict:
    """One _assess_symbol-shaped entry; the degraded shape mirrors
    ``_minimal_risk`` (metrics carry only the beta status key)."""
    if not enriched:
        return {
            "symbol": "TEST",
            "risk_score": None,
            "risk_level": "insufficient_data",
            "risk_score_status": "insufficient_data",
            "metrics": {"beta": None, "beta_status": "insufficient_data"},
            "position_recommendation": {
                "max_position_size": None,
                "status": "insufficient_data",
            },
            "warnings": ["Insufficient data for detailed risk assessment"],
        }
    return {
        "symbol": "TEST",
        "risk_score": 42.0,
        "risk_level": "medium",
        "risk_score_status": "complete",
        "metrics": {
            "beta": 1.2,
            "volatility_annualized": 0.31,
            "var_95": -0.037,
            "max_drawdown": 0.24,
            "alpha_annualized": 0.05,
        },
        "position_recommendation": {"max_position_size": 10.0, "status": "available"},
        "warnings": [],
        "liquidity": {
            "adv_20d": 1_500_000.0,
            "currency": "USD",
            "level": "thin",
            "min_adv": 2_000_000.0,
            "status": "available",
        },
        "sector_relative": {
            "sector": "Technology",
            "benchmark_ticker": "XLK",
            "beta_sector": 2.0,
            "alpha_annualized_sector": 0.11,
            "r_squared_sector": 0.9,
            "correlation_sector": 0.95,
            "status": "available",
        },
    }


def _data(enriched: bool) -> dict:
    return {
        "symbols": ["TEST"],
        "query": "TEST passthrough",
        "risk_assessment": {
            "risk_by_symbol": {"TEST": _risk_entry(enriched)},
            "portfolio_risk": {
                "correlations": {
                    "status": "available",
                    "aligned_days": 250,
                    "pairs": [{"pair": ["TEST", "BENCH"], "correlation": 0.8}],
                },
                "avg_pairwise_correlation": 0.8,
                "diversification_score": 30.0,
            },
            "overall_risk_level": "medium",
        },
    }


class TestRiskAnnotationPassthrough:
    def test_liquidity_and_sector_blocks_reach_the_report(self) -> None:
        sections = ReportService.build_sections(_data(enriched=True))

        card = sections["risk_analysis"]["by_symbol"]["TEST"]
        assert card["liquidity"]["level"] == "thin"
        assert card["liquidity"]["adv_20d"] == 1_500_000.0
        assert card["sector_relative"]["beta_sector"] == 2.0
        assert card["sector_relative"]["benchmark_ticker"] == "XLK"
        # The headline risk metrics ride along on the same card.
        assert card["var_95"] == -0.037
        assert card["max_drawdown"] == 0.24
        assert card["alpha_annualized"] == 0.05

    def test_degraded_entries_gain_no_annotation_keys(self) -> None:
        sections = ReportService.build_sections(_data(enriched=False))

        card = sections["risk_analysis"]["by_symbol"]["TEST"]
        assert "liquidity" not in card
        assert "sector_relative" not in card
        # Missing metrics pass through as None — honest absence, not 0.
        assert card["var_95"] is None
        assert card["max_drawdown"] is None
        assert card["alpha_annualized"] is None
        assert card["risk_score"] is None

    def test_portfolio_correlations_survive_the_section(self) -> None:
        sections = ReportService.build_sections(_data(enriched=True))

        portfolio = sections["risk_analysis"]["portfolio_risk"]
        assert portfolio["correlations"]["pairs"][0]["pair"] == ["TEST", "BENCH"]
        assert portfolio["avg_pairwise_correlation"] == 0.8
        assert portfolio["diversification_score"] == 30.0


def _regime_block() -> dict:
    return {
        "status": "ok",
        "bars": 300,
        "trend": "bull",
        "volatility_regime": "normal",
        "drawdown_from_52w_high": -0.0312,
        "price_vs_sma200": 0.0641,
        "vol_ratio_20d_vs_full": 0.98,
    }


class TestMarketRegimePassthrough:
    def test_regime_reaches_the_risk_section(self) -> None:
        data = _data(enriched=True)
        data["risk_assessment"]["market_regime"] = _regime_block()

        regime = ReportService.build_sections(data)["risk_analysis"]["market_regime"]

        assert regime == _regime_block()

    def test_missing_regime_passes_through_as_none(self) -> None:
        # Pre-iteration-76 records (and benchmark-less runs) carry no regime
        # key at all — the section still renders, with an honest None.
        regime = ReportService.build_sections(_data(enriched=True))["risk_analysis"][
            "market_regime"
        ]
        assert regime is None
