"""ReAct-path market-regime consumption in the report layer.

``assess_risk`` (ReAct) attaches a ``market_regime`` block beside the flat
per-symbol risk map. ``_normalize``'s flat branch must lift it out — both
so the risk section carries it to the frontend regime block and so the
namespaced key can never leak into the per-symbol map. The derived
recommendation path (no decision agent on ReAct) must also surface the
same decision-layer warnings the pipeline decisions carry: the pure
warning generators live in ``app/analysis/regime.py`` and are consumed
post-derive, so both paths speak with one voice.
"""

from __future__ import annotations

from app.services.report_service import ReportService

BEAR_REGIME = {
    "status": "ok",
    "bars": 210,
    "trend": "bear",
    "price_vs_sma200": -0.417,
    # Both extra warning conditions deliberately OFF — the counter-trend
    # warning must fire alone, not buried among neighbors.
    "volatility_regime": "normal",
    "drawdown_from_52w_high": -0.05,
}

HEALTHY_TECH = {"signals": {"trend": "bullish"}, "sentiment": {"score": 80}}


def _data(with_regime: bool = True, with_technical: bool = True) -> dict:
    data: dict = {
        "symbols": ["TEST"],
        "query": "TEST",
        "fundamental_analysis": {"TEST": {"overall_score": {"score": 80}}},
        "risk_assessment": {
            "TEST": {"symbol": "TEST", "risk_score": 45, "risk_level": "medium", "metrics": {}},
        },
    }
    if with_technical:
        data["technical_analysis"] = {"TEST": HEALTHY_TECH}
    if with_regime:
        data["risk_assessment"]["market_regime"] = BEAR_REGIME
    return data


def _sections(data: dict) -> dict:
    return ReportService.build_sections(data)


class TestFlatRegimeExtraction:
    def test_regime_reaches_risk_section_and_is_stripped_from_flat_map(self) -> None:
        sections = _sections(_data(with_regime=True))

        risk = sections["risk_analysis"]
        assert risk["market_regime"] == BEAR_REGIME
        assert set(risk["by_symbol"].keys()) == {"TEST"}

    def test_no_regime_leaves_section_without_key(self) -> None:
        risk = _sections(_data(with_regime=False))["risk_analysis"]

        assert risk.get("market_regime") is None


class TestDerivedRegimeWarnings:
    def test_buy_in_bear_regime_carries_counter_trend_warning(self) -> None:
        recs = _sections(_data(with_regime=True))["recommendations"]
        rec = recs["by_symbol"]["TEST"]

        assert rec["action"] == "buy"
        assert len(rec["warnings"]) == 1
        assert "Counter-trend entry" in rec["warnings"][0]

    def test_buy_without_regime_omits_warnings(self) -> None:
        rec = _sections(_data(with_regime=False))["recommendations"]["by_symbol"]["TEST"]

        assert rec["action"] == "buy"
        assert "warnings" not in rec

    def test_gated_hold_low_confidence_warns(self) -> None:
        rec = _sections(_data(with_regime=True, with_technical=False))["recommendations"][
            "by_symbol"
        ]["TEST"]

        assert rec["action"] == "hold"
        assert rec["warnings"] == [
            "Low confidence in this recommendation. Consider waiting for clearer signals."
        ]
