"""Market-regime attachment in the ReAct risk tool.

The pipeline risk agent has classified the market regime from the run's
benchmark since iteration 76; the ReAct ``assess_risk`` tool consumes the
same attached benchmark for beta/alpha/R² but never classified it — every
ReAct report shipped ``market_regime: None``, so the frontend regime block
never rendered on that path and the regime-conditional buyer warnings were
structurally impossible. The tool must attach ONE regime block for the run
(same benchmark → same market, keyed ``market_regime`` beside the
per-symbol entries) and omit the key entirely without a benchmark —
degraded runs stay honest instead of fabricating a regime.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.tools.risk.assessment import assess_risk


def _history(closes: list[float]) -> dict[str, list]:
    dates = [(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(len(closes))]
    return {"dates": dates, "close": closes}


def _bear_benchmark(bars: int = 210) -> dict[str, list]:
    """Declining benchmark with VARYING returns.

    A constant-return tape is zero-variance and the classifier rejects it
    outright (iteration 76 fixture lesson) — alternate two negative steps
    so the series declines ~0.6%/bar with real dispersion.
    """
    closes = [100.0]
    for i in range(bars - 1):
        step = -0.010 if i % 2 == 0 else -0.002
        closes.append(closes[-1] * (1 + step))
    return _history(closes)


def _mild_stock(bars: int = 80) -> dict[str, list]:
    closes = [100.0 * (1.001**i) for i in range(bars)]
    return _history(closes)


class TestRegimeAttach:
    def test_shared_benchmark_yields_one_regime_block(self) -> None:
        bench = _bear_benchmark()
        market_data = {
            "TEST": {
                "symbol": "TEST",
                "historical_data": _mild_stock(),
                "benchmark_historical_data": bench,
            },
            "TEST2": {
                "symbol": "TEST2",
                "historical_data": _mild_stock(),
                "benchmark_historical_data": bench,
            },
        }

        result = assess_risk.invoke({"market_data": market_data})

        regime = result.get("market_regime")
        assert isinstance(regime, dict)
        assert regime["status"] == "ok"
        assert regime["trend"] == "bear"
        assert regime["bars"] == 210
        # The namespaced key rides beside real symbol entries — both intact.
        assert result["TEST"]["symbol"] == "TEST"
        assert result["TEST2"]["symbol"] == "TEST2"

    def test_no_benchmark_omits_regime(self) -> None:
        market_data = {"TEST": {"symbol": "TEST", "historical_data": _mild_stock()}}

        result = assess_risk.invoke({"market_data": market_data})

        assert "market_regime" not in result
