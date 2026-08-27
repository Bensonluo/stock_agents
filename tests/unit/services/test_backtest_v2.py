"""Tests for the V2 backtest service methods (data source mocked)."""

from __future__ import annotations

import pandas as pd
import pytest

from app.services.backtest_service import BacktestService


def _ohlc(days: int = 400) -> pd.DataFrame:
    # Dip first, then recover: gives SMA crossovers on a deterministic series.
    decline = [100.0 * (0.998**i) for i in range(days // 3)]
    trough = decline[-1]
    rise = [trough * (1.002**i) for i in range(days - days // 3)]
    closes = decline + rise
    opens = [closes[0]] + closes[:-1]
    index = pd.bdate_range("2024-01-01", periods=days)
    return pd.DataFrame(
        {
            "Open": opens,
            "High": [max(o, c) for o, c in zip(opens, closes)],
            "Low": [min(o, c) for o, c in zip(opens, closes)],
            "Close": closes,
            "Volume": [1_000_000.0] * days,
        },
        index=index,
    )


@pytest.fixture
def service(monkeypatch) -> BacktestService:
    svc = BacktestService()

    async def fake_fetch(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        return _ohlc()

    monkeypatch.setattr(svc, "_fetch_data", fake_fetch)
    return svc


class TestRunBacktestV2:
    @pytest.mark.asyncio
    async def test_returns_full_metrics_and_manifest(self, service: BacktestService) -> None:
        result = await service.run_backtest_v2(
            symbol="AAPL",
            strategy="sma_crossover",
            start_date="2024-01-01",
            end_date="2025-12-31",
            strategy_params={"sma_short": 10, "sma_long": 40},
        )

        assert result["symbol"] == "AAPL"
        assert result["params"] == {"sma_short": 10, "sma_long": 40}
        assert "sharpe" in result["metrics"]
        assert result["manifest"]["data_sha256"]
        assert result["manifest"]["bars"] == 400
        assert len(result["equity"]) == 400
        assert result["trades"][0]["action"] == "buy"

    @pytest.mark.asyncio
    async def test_benchmark_produces_excess(self, service: BacktestService) -> None:
        result = await service.run_backtest_v2(
            symbol="AAPL",
            strategy="buy_and_hold",
            start_date="2024-01-01",
            end_date="2025-12-31",
            benchmark_symbol="^GSPC",
        )

        assert result["benchmark_equity"] is not None
        assert result["metrics"]["excess_vs_benchmark"] == pytest.approx(0.0, abs=1e-9)

    @pytest.mark.asyncio
    async def test_unknown_market_preset_rejected(self, service: BacktestService) -> None:
        with pytest.raises(ValueError, match="Unknown market preset"):
            await service.run_backtest_v2(
                symbol="AAPL",
                strategy="buy_and_hold",
                start_date="2024-01-01",
                end_date="2025-12-31",
                market="moon",
            )


class TestWalkForwardService:
    @pytest.mark.asyncio
    async def test_report_includes_windows_and_manifest(self, service: BacktestService) -> None:
        report = await service.run_walk_forward(
            symbol="AAPL",
            strategy="sma_crossover",
            start_date="2024-01-01",
            end_date="2025-12-31",
            param_grid={"sma_short": [5, 10], "sma_long": [30, 60]},
            train_bars=120,
            test_bars=40,
        )

        assert report["windows"], "expected windows"
        assert report["aggregate"]["windows_run"] == len(report["windows"])
        assert report["manifest"]["configs_tested"] == 4 * len(report["windows"])

    @pytest.mark.asyncio
    async def test_not_enough_data_reported(self, monkeypatch) -> None:
        svc = BacktestService()

        async def tiny_fetch(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
            return _ohlc(60)

        monkeypatch.setattr(svc, "_fetch_data", tiny_fetch)
        report = await svc.run_walk_forward(
            symbol="AAPL",
            strategy="sma_crossover",
            start_date="2024-01-01",
            end_date="2024-03-31",
            param_grid={"sma_short": [5], "sma_long": [20]},
            train_bars=200,
            test_bars=50,
        )

        assert report["windows"] == []
        assert "error" in report["aggregate"]
