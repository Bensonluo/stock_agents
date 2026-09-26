"""Functional tests for the V2 backtest API endpoints (real engine, mocked feed)."""

from __future__ import annotations

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.routes.backtest as backtest_route
from app.services.backtest_service import BacktestService


def _market(days: int = 400) -> pd.DataFrame:
    """Deterministic dip-then-rise frame (crossovers guaranteed)."""
    decline = [200.0 * (0.9985**i) for i in range(days // 3)]
    rise = [decline[-1] * (1.0025**i) for i in range(days - days // 3)]
    closes = decline + rise
    opens = [closes[0]] + closes[:-1]
    index = pd.bdate_range("2024-01-01", periods=days)
    return pd.DataFrame(
        {
            "Open": opens,
            "High": [max(o, c) * 1.01 for o, c in zip(opens, closes)],
            "Low": [min(o, c) * 0.99 for o, c in zip(opens, closes)],
            "Close": closes,
            "Volume": [1_000_000.0] * days,
        },
        index=index,
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def fake_fetch(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        return _market()

    monkeypatch.setattr(BacktestService, "_fetch_data", fake_fetch)
    app = FastAPI()
    app.include_router(backtest_route.router, prefix="/api/backtest")
    return TestClient(app)


class TestV2RunEndpoint:
    def test_full_payload_through_the_real_engine(self, client: TestClient) -> None:
        response = client.post(
            "/api/backtest/v2/run",
            json={
                "symbol": "AAPL",
                "strategy": "sma_crossover",
                "start_date": "2024-01-01",
                "end_date": "2025-12-31",
                "strategy_params": {"sma_short": 10, "sma_long": 40},
                "benchmark_symbol": "^GSPC",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["symbol"] == "AAPL"
        assert body["params"] == {"sma_short": 10, "sma_long": 40}
        for key in ("total_return", "cagr", "sharpe", "max_drawdown", "cvar_95_daily"):
            assert key in body["metrics"], f"missing metric {key}"
        assert body["benchmark_equity"] is not None
        assert body["metrics"]["excess_vs_benchmark"] is not None
        assert len(body["equity"]) == 400
        assert body["trades"][0]["action"] == "buy"
        assert body["manifest"]["data_sha256"]
        assert "execution_time" in body

    def test_cn_market_preset_applies_stamp_tax(self, client: TestClient) -> None:
        response = client.post(
            "/api/backtest/v2/run",
            json={
                "symbol": "600519",
                "strategy": "buy_and_hold",
                "start_date": "2024-01-01",
                "end_date": "2025-12-31",
                "market": "cn",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["manifest"]["cost_model"]["stamp_tax"] == 0.0005
        assert body["metrics"]["cost_ratio"] > 0

    @pytest.mark.parametrize(
        "overrides",
        [
            {"market": "hk"},  # unknown preset
            {"strategy": "moon_shot"},  # unknown strategy
            {"strategy_params": {"rsi_period": 14}},  # wrong strategy's param
            {"start_date": "2025-12-31", "end_date": "2024-01-01"},  # reversed dates
            {"symbol": "not a symbol!"},  # invalid symbol
        ],
    )
    def test_invalid_requests_rejected(self, client: TestClient, overrides: dict) -> None:
        payload = {
            "symbol": "AAPL",
            "strategy": "sma_crossover",
            "start_date": "2024-01-01",
            "end_date": "2025-12-31",
        }
        payload.update(overrides)
        assert client.post("/api/backtest/v2/run", json=payload).status_code == 422


class TestWalkforwardEndpoint:
    def test_windows_and_manifest(self, client: TestClient) -> None:
        response = client.post(
            "/api/backtest/v2/walkforward",
            json={
                "symbol": "AAPL",
                "strategy": "sma_crossover",
                "start_date": "2024-01-01",
                "end_date": "2025-12-31",
                "param_grid": {"sma_short": [5, 10], "sma_long": [30, 60]},
                "train_bars": 120,
                "test_bars": 60,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["windows"], "expected walk-forward windows"
        assert body["configs_tested"] == 4 * len(body["windows"])
        assert body["aggregate"]["windows_run"] == len(body["windows"])
        assert body["manifest"]["configs_tested"] == body["configs_tested"]

    def test_bad_horizon_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/api/backtest/v2/walkforward",
            json={
                "symbol": "AAPL",
                "strategy": "buy_and_hold",
                "start_date": "2024-01-01",
                "end_date": "2025-12-31",
                "param_grid": {},
                "train_bars": 10,
                "test_bars": 60,
            },
        )
        assert response.status_code == 422


class TestCalibrateEndpoint:
    def test_hit_rate_report(self, client: TestClient) -> None:
        response = client.post(
            "/api/backtest/v2/calibrate",
            json={
                "symbol": "AAPL",
                "strategy": "sma_crossover",
                "start_date": "2024-01-01",
                "end_date": "2025-12-31",
                "horizons": [20],
                "strategy_params": {"sma_short": 10, "sma_long": 40},
            },
        )

        assert response.status_code == 200
        horizon = response.json()["by_horizon"]["20"]
        assert horizon["events"] > 0
        assert horizon["wilson_lower"] <= horizon["hit_rate"]
        assert response.json()["manifest"]["strategy"] == "sma_crossover"


class TestLegacyRunEndpoint:
    def test_technical_score_through_legacy_endpoint(self, client: TestClient) -> None:
        """Frontend path: the form posts the flat score_threshold field; the
        legacy endpoint used to 500 because the service's hand-maintained
        parameter dict omitted technical_score."""
        response = client.post(
            "/api/backtest/run",
            json={
                "symbol": "AAPL",
                "strategy": "technical_score",
                "start_date": "2024-01-01",
                "end_date": "2025-12-31",
                "score_threshold": 10,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["strategy"] == "technical_score"
        for key in ("final_value", "total_return_pct", "sharpe_ratio", "max_drawdown"):
            assert key in body
        assert len(body["equity"]) == 400

    def test_sma_crossover_params_still_pass(self, client: TestClient) -> None:
        # Regression: named parameters through the legacy contract.
        response = client.post(
            "/api/backtest/run",
            json={
                "symbol": "AAPL",
                "strategy": "sma_crossover",
                "start_date": "2024-01-01",
                "end_date": "2025-12-31",
                "sma_short": 10,
                "sma_long": 40,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["strategy"] == "sma_crossover"
        assert body["total_trades"] >= 1

    def test_legacy_contract_backed_by_the_v2_engine(self, client: TestClient) -> None:
        response = client.post(
            "/api/backtest/run",
            json={
                "symbol": "AAPL",
                "strategy": "buy_and_hold",
                "start_date": "2024-01-01",
                "end_date": "2025-12-31",
            },
        )

        assert response.status_code == 200
        body = response.json()
        # The legacy response model fields must all be present and numeric.
        for key in (
            "final_value",
            "total_return",
            "total_return_pct",
            "annual_return",
            "sharpe_ratio",
            "max_drawdown",
            "win_rate",
            "total_trades",
            "equity",
        ):
            assert key in body
        assert body["final_value"] > 0
        assert body["total_trades"] >= 1  # force-liquidation guarantees a round trip
        assert len(body["equity"]) == 400
