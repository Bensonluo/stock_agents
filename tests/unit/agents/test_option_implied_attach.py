"""Option-implied annotation attachment: data agent fetch, risk agent label.

Iteration 155: runs containing CN symbols carry one market-level
``option_snapshot`` (SSE per-contract IV/Greeks + official PCR + QVIX
context); the risk agent turns it into one ``option_implied`` regime block
(恐慌/中性/自满) — PURE ANNOTATION, no scoring path may read it. These
tests pin the wiring (CN-gated fetch, never on US-only runs, toggle off),
the attach conventions, and the annotation-only contract.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

import app.agents.data_agent as data_agent_mod
from app.config import get_settings
from app.tools.data import fetcher_common
from app.tools.data.provider_health import reset_provider_health


def _load_risk_agent_class() -> type:
    """Load risk_agent without exercising the app's unrelated package cycle."""
    base_module = ModuleType("app.agents.base")
    base_module.StatelessAgent = type("StatelessAgent", (), {})
    state_module = ModuleType("app.orchestration.state")
    state_module.AgentState = dict

    replaced = {
        name: sys.modules.get(name) for name in ("app.agents.base", "app.orchestration.state")
    }
    sys.modules.update({"app.agents.base": base_module, "app.orchestration.state": state_module})
    try:
        module_path = Path(__file__).parents[3] / "app" / "agents" / "risk_agent.py"
        spec = importlib.util.spec_from_file_location("risk_agent_option_test", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.RiskAssessmentAgent
    finally:
        for name, original in replaced.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


RiskAssessmentAgent = _load_risk_agent_class()


@pytest.fixture(autouse=True)
def _clean_state():
    reset_provider_health()
    for key in ("option_snapshot", "qvix_context"):
        fetcher_common._cache.pop(key, None)
    yield
    reset_provider_health()
    for key in ("option_snapshot", "qvix_context"):
        fetcher_common._cache.pop(key, None)


# ---------------------------------------------------------------------------
# Data agent wiring
# ---------------------------------------------------------------------------


def _snapshot_stub() -> dict[str, Any]:
    return {
        "status": "ok",
        "as_of": "2026-09-29",
        "contracts": [
            {
                "contract_id": "10005001",
                "symbol": "510050",
                "cp": "C",
                "strike": 2.90,
                "expire_date": "2026-09-24",
                "delta": 0.50,
                "iv": 0.185,
            }
        ],
        "pcr_by_underlying": {
            "510050": {
                "name": "上证50ETF",
                "pcr_volume": 0.9,
                "call_volume": 1000.0,
                "put_volume": 900.0,
                "trade_date": "2026-09-29",
            }
        },
        "n_unmatched": 0,
        "qvix_context": _qvix_stub(),
    }


def _qvix_stub() -> dict[str, Any]:
    return {"current": 21.0, "as_of": "2026-09-29", "percentile_1y": 0.45, "history_days": 300}


async def _no_benchmarks(*_args: Any, **_kwargs: Any) -> None:
    return None


def _patch_collection(monkeypatch: pytest.MonkeyPatch, symbols: list[str]) -> None:
    async def fake_collect(self, symbol: str) -> dict[str, Any]:
        return {
            "market_data": {"symbol": symbol, "sector": None, "historical_data": {}},
            "financial_data": {},
            "news_data": [],
        }

    monkeypatch.setattr(data_agent_mod.DataCollectionAgent, "_collect_symbol_data", fake_collect)
    monkeypatch.setattr(data_agent_mod, "fetch_benchmark_history", _no_benchmarks)
    monkeypatch.setattr(data_agent_mod, "fetch_cn_sector_benchmark", _no_benchmarks)
    monkeypatch.setattr(data_agent_mod, "fetch_cn_consensus", _no_benchmarks)
    monkeypatch.setattr(data_agent_mod, "sector_benchmark_ticker", lambda sector: None)


class TestDataAgentOptionSnapshotAttach:
    @pytest.mark.asyncio
    async def test_cn_run_attaches_snapshot_with_qvix_context(self, monkeypatch) -> None:
        _patch_collection(monkeypatch, ["600000"])
        fetch_calls: list[str] = []
        monkeypatch.setattr(
            data_agent_mod,
            "fetch_sse_option_snapshot",
            lambda: (fetch_calls.append("sse"), _snapshot_stub())[1],
        )
        monkeypatch.setattr(data_agent_mod, "fetch_qvix_context", lambda store: _qvix_stub())

        result = await data_agent_mod.DataCollectionAgent(name="data_collection").execute(
            {"symbols": ["600000"]}
        )

        assert fetch_calls == ["sse"]
        snapshot = result["option_snapshot"]
        assert snapshot["as_of"] == "2026-09-29"
        assert snapshot["contracts"][0]["iv"] == pytest.approx(0.185)
        assert snapshot["qvix_context"]["percentile_1y"] == 0.45

    @pytest.mark.asyncio
    async def test_us_only_run_never_fetches_options(self, monkeypatch) -> None:
        _patch_collection(monkeypatch, ["AAPL"])
        fetch_calls: list[str] = []
        monkeypatch.setattr(
            data_agent_mod,
            "fetch_sse_option_snapshot",
            lambda: (fetch_calls.append("sse"), _snapshot_stub())[1],
        )
        monkeypatch.setattr(data_agent_mod, "fetch_qvix_context", lambda store: _qvix_stub())

        result = await data_agent_mod.DataCollectionAgent(name="data_collection").execute(
            {"symbols": ["AAPL"]}
        )

        assert fetch_calls == []
        assert "option_snapshot" not in result

    @pytest.mark.asyncio
    async def test_toggle_off_never_fetches_options(self, monkeypatch) -> None:
        _patch_collection(monkeypatch, ["600000"])
        monkeypatch.setattr(get_settings(), "option_signals_enabled", False)
        fetch_calls: list[str] = []
        monkeypatch.setattr(
            data_agent_mod,
            "fetch_sse_option_snapshot",
            lambda: (fetch_calls.append("sse"), _snapshot_stub())[1],
        )
        monkeypatch.setattr(data_agent_mod, "fetch_qvix_context", lambda store: _qvix_stub())

        result = await data_agent_mod.DataCollectionAgent(name="data_collection").execute(
            {"symbols": ["600000"]}
        )

        assert fetch_calls == []
        assert "option_snapshot" not in result

    @pytest.mark.asyncio
    async def test_fetch_failure_leaves_key_absent(self, monkeypatch) -> None:
        _patch_collection(monkeypatch, ["600000"])
        monkeypatch.setattr(data_agent_mod, "fetch_sse_option_snapshot", lambda: None)
        monkeypatch.setattr(data_agent_mod, "fetch_qvix_context", lambda store: None)

        result = await data_agent_mod.DataCollectionAgent(name="data_collection").execute(
            {"symbols": ["600000"]}
        )

        assert "option_snapshot" not in result


# ---------------------------------------------------------------------------
# Risk agent wiring
# ---------------------------------------------------------------------------


def _history(bars: int = 80) -> dict[str, list]:
    """A mild up-trending tape with real dispersion (zero-variance is rejected)."""
    closes = [100.0]
    for i in range(bars - 1):
        step = 0.004 if i % 2 == 0 else -0.001
        closes.append(closes[-1] * (1 + step))
    start = date(2025, 1, 1)
    return {
        "dates": [(start + timedelta(days=i)).isoformat() for i in range(bars)],
        "close": closes,
    }


def _market_data() -> dict[str, Any]:
    return {
        "600000": {"symbol": "600000", "historical_data": _history()},
    }


def _state_with_snapshot() -> dict[str, Any]:
    return {
        "symbols": ["600000"],
        "market_data": _market_data(),
        "option_snapshot": _snapshot_stub(),
    }


class TestRiskAgentOptionImplied:
    def test_snapshot_present_builds_the_annotation_block(self) -> None:
        agent = RiskAssessmentAgent()

        block = agent._option_implied(_state_with_snapshot())

        assert block is not None
        assert block["status"] == "ok"
        assert block["regime"] == "中性"  # percentile 0.45
        assert block["qvix"] == _qvix_stub()
        assert block["pcr"]["market_pcr"] == pytest.approx(0.9)
        assert block["generated_at"]

    def test_snapshot_absent_returns_none(self) -> None:
        agent = RiskAssessmentAgent()

        assert agent._option_implied({}) is None
        assert agent._option_implied({"option_snapshot": None}) is None

    @pytest.mark.asyncio
    async def test_process_attaches_option_implied_key(self) -> None:
        agent = RiskAssessmentAgent()

        result = await agent.process(_state_with_snapshot())

        assert isinstance(result.get("option_implied"), dict)
        assert result["option_implied"]["regime"] == "中性"

    @pytest.mark.asyncio
    async def test_process_without_snapshot_follows_regime_none_convention(self) -> None:
        agent = RiskAssessmentAgent()

        result = await agent.process({"symbols": ["600000"], "market_data": _market_data()})

        # market_regime's None convention: key present, value None.
        assert result["market_regime"] is None or isinstance(result["market_regime"], dict)
        assert "option_implied" in result
        assert result["option_implied"] is None

    @pytest.mark.asyncio
    async def test_pure_annotation_scores_are_byte_identical(self) -> None:
        """No scoring path may read the option block — outputs must match exactly."""
        agent = RiskAssessmentAgent()

        with_options = await agent.process(_state_with_snapshot())
        without_options = await agent.process(
            {"symbols": ["600000"], "market_data": _market_data()}
        )

        assert with_options["risk_by_symbol"] == without_options["risk_by_symbol"]
        assert with_options["portfolio_risk"] == without_options["portfolio_risk"]
        assert with_options["overall_risk_level"] == without_options["overall_risk_level"]
        assert with_options["market_regime"] == without_options["market_regime"]
