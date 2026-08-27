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


class TestCalibrateService:
    @pytest.mark.asyncio
    async def test_calibration_report_with_manifest(self, service: BacktestService) -> None:
        report = await service.calibrate_signals(
            symbol="AAPL",
            strategy="sma_crossover",
            start_date="2024-01-01",
            end_date="2025-12-31",
            horizons=[20],
            strategy_params={"sma_short": 10, "sma_long": 40},
        )

        assert report["strategy"] == "sma_crossover"
        assert "20" in report["by_horizon"]
        assert report["manifest"]["data_sha256"]


class TestProviderChainFallback:
    @pytest.mark.asyncio
    async def test_yfinance_failure_falls_back_to_shared_chain(self, monkeypatch) -> None:
        import numpy as np

        service = BacktestService()

        class RateLimited(Exception):
            pass

        def broken_ticker(symbol: str):
            raise RateLimited("Too Many Requests")

        monkeypatch.setattr("app.services.backtest_service.yf.Ticker", broken_ticker)

        async def fake_chain(symbol: str, period: str = "3y") -> dict:
            days = 300
            closes = [100.0 * (1.001**i) for i in range(days)]
            return {
                "dates": [d.isoformat() for d in pd.bdate_range("2024-01-01", periods=days)],
                "open": closes, "high": closes, "low": closes,
                "close": closes, "volume": [1e6] * days,
            }

        monkeypatch.setattr("app.tools.data.fetcher.fetch_historical", fake_chain)

        result = await service.run_backtest(
            symbol="AAPL", strategy="buy_and_hold",
            start_date="2024-06-01", end_date="2025-06-01",
        )

        assert result["final_value"] > 0
        assert result["total_trades"] >= 1

    @pytest.mark.asyncio
    async def test_chain_exhausted_raises_value_error(self, monkeypatch) -> None:
        service = BacktestService()

        async def empty_chain(symbol: str, period: str = "3y") -> dict:
            return {"dates": [], "close": []}

        monkeypatch.setattr("app.tools.data.fetcher.fetch_historical", empty_chain)

        def broken_ticker(symbol: str):
            raise RuntimeError("rate limited")

        monkeypatch.setattr("app.services.backtest_service.yf.Ticker", broken_ticker)

        with pytest.raises(ValueError, match="No data available"):
            await service._fetch_data("AAPL", "2024-01-01", "2025-01-01")


class TestStooqLastResort:
    @pytest.mark.asyncio
    async def test_chain_ends_at_stooq_csv(self, monkeypatch) -> None:
        """yfinance limited + others down: stooq CSV must rescue the backtest."""
        from io import StringIO

        import app.tools.data.fetcher as fetcher

        days = 300
        closes = [100.0 * (1.001**i) for i in range(days)]
        dates = pd.bdate_range("2024-01-01", periods=days).strftime("%Y-%m-%d")

        class FakeResponse:
            text = "\n".join(
                ["Date,Open,High,Low,Close,Volume"]
                + [
                    f"{d},{c},{c},{c},{c},1000000"
                    for d, c in zip(dates, closes)
                ]
            )

            def raise_for_status(self):
                return None

        monkeypatch.setattr(fetcher.requests, "get", lambda *a, **kw: FakeResponse())

        def broken_ticker(symbol: str):
            raise RuntimeError("Too Many Requests")

        monkeypatch.setattr("app.services.backtest_service.yf.Ticker", broken_ticker)

        # akshare/yahoo-api also fail naturally for a bogus env; force them off
        async def failing(*args, **kwargs):
            raise RuntimeError("down")

        monkeypatch.setattr(fetcher, "_akshare_hist_ok", lambda: False, raising=False)

        service = BacktestService()
        result = await service.run_backtest(
            symbol="AAPL", strategy="buy_and_hold",
            start_date="2024-03-01", end_date="2025-06-01",
        )
        assert result["final_value"] > 0
