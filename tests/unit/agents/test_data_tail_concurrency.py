"""Concurrency pin for the data agent's four tail fetches.

``execute`` collects per-symbol data first, then runs four independent
annotation fetches — per-market benchmarks, SPDR sector benchmarks, CN
industry benchmarks and the CN option snapshot. None of them reads another
leg's result, and their writes are disjoint (the SPDR sector map excludes
CN symbols so the CN industry loop keeps its unconditional write), so they
all run in one ``asyncio.gather``: worst-case wall time is the slowest leg,
not the sum. The first test deadlocks by construction under sequential
execution — the market-benchmark fake blocks on an Event that only the CN
benchmark fake sets, which itself waits on one that only the option fake
sets.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

import app.agents.data_agent as data_agent_mod
from app.config import get_settings

pytestmark = pytest.mark.asyncio


def _bench(ticker: str) -> dict[str, Any]:
    return {"symbol": ticker, "dates": ["2026-01-02"], "close": [4800.0]}


def _cn_bench() -> dict[str, Any]:
    return {"symbol": "银行", "dates": ["2026-01-02"], "close": [2400.0]}


def _patch_collection(monkeypatch: pytest.MonkeyPatch, markets: dict[str, dict[str, Any]]) -> None:
    """Stub per-symbol collection so execute() exercises only the tail gather."""

    async def _fake_collect(self, symbol: str) -> dict[str, Any]:
        return {
            "market_data": {"symbol": symbol, **markets.get(symbol, {})},
            "financial_data": {},
            "news_data": [],
        }

    monkeypatch.setattr(data_agent_mod.DataCollectionAgent, "_collect_symbol_data", _fake_collect)


async def test_tail_fetches_run_concurrently(monkeypatch: pytest.MonkeyPatch) -> None:
    """Market benchmark, CN industry benchmark and the option snapshot must
    overlap. The option fake sets opt_ran; the CN benchmark fake waits for
    opt_ran then sets cn_ran; the market-benchmark fake waits for cn_ran.
    Sequential execution deadlocks past the wait_for budget (the option leg
    runs last); under gather the chain resolves and every key attaches."""
    opt_ran = asyncio.Event()
    cn_ran = asyncio.Event()

    async def _fake_option_snapshot(self) -> dict[str, Any]:
        opt_ran.set()
        return {"status": "ok"}

    async def _fake_cn_benchmark(symbol: str) -> dict[str, Any]:
        await opt_ran.wait()  # only resolvable while the option leg is running
        cn_ran.set()
        return _cn_bench()

    async def _fake_market_benchmark(ticker: str) -> dict[str, Any]:
        if ticker == data_agent_mod.BENCHMARK_TICKERS["cn"]:
            await cn_ran.wait()  # only resolvable while the CN leg is running
        return _bench(ticker)

    _patch_collection(monkeypatch, {})
    monkeypatch.setattr(get_settings(), "option_signals_enabled", True)
    monkeypatch.setattr(
        data_agent_mod.DataCollectionAgent, "_fetch_option_snapshot", _fake_option_snapshot
    )
    monkeypatch.setattr(data_agent_mod, "fetch_benchmark_history", _fake_market_benchmark)
    monkeypatch.setattr(data_agent_mod, "fetch_cn_sector_benchmark", _fake_cn_benchmark)

    agent = data_agent_mod.DataCollectionAgent(name="data_collection")
    result = await asyncio.wait_for(agent.execute({"symbols": ["600000"]}), timeout=5.0)

    cn_block = result["market_data"]["600000"]
    assert cn_block["benchmark_historical_data"]["symbol"] == data_agent_mod.BENCHMARK_TICKERS["cn"]
    assert cn_block["sector_benchmark_historical_data"]["symbol"] == "银行"
    assert result["option_snapshot"] == {"status": "ok"}


async def test_cn_sector_field_never_fetches_spdr(monkeypatch: pytest.MonkeyPatch) -> None:
    """A CN block carrying a mapped sector field must not send it down the
    SPDR path — the sector map excludes CN symbols structurally, and the CN
    industry benchmark owns their sector_benchmark_historical_data."""
    fetched: list[str] = []

    async def _fake_market_benchmark(ticker: str) -> dict[str, Any]:
        fetched.append(ticker)
        return _bench(ticker)

    async def _fake_cn_benchmark(symbol: str) -> dict[str, Any]:
        return _cn_bench()

    _patch_collection(monkeypatch, {"600000": {"sector": "Technology"}})
    monkeypatch.setattr(get_settings(), "option_signals_enabled", False)
    monkeypatch.setattr(data_agent_mod, "fetch_benchmark_history", _fake_market_benchmark)
    monkeypatch.setattr(data_agent_mod, "fetch_cn_sector_benchmark", _fake_cn_benchmark)

    agent = data_agent_mod.DataCollectionAgent(name="data_collection")
    result = await agent.execute({"symbols": ["600000"]})

    # Only the market index round-tripped — never the SPDR sector ETF, even
    # though the CN block carried a mappable sector string.
    assert fetched == [data_agent_mod.BENCHMARK_TICKERS["cn"]]
    assert result["market_data"]["600000"]["sector_benchmark_historical_data"]["symbol"] == "银行"


async def test_mixed_run_attaches_expected_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same inputs → same final market_data shape as the sequential tail:
    US symbols get market + SPDR sector benchmarks, CN symbols get market +
    industry benchmark, and the option snapshot rides along on CN runs."""
    fetched: list[str] = []

    async def _fake_market_benchmark(ticker: str) -> dict[str, Any]:
        fetched.append(ticker)
        return _bench(ticker)

    async def _fake_cn_benchmark(symbol: str) -> dict[str, Any]:
        return _cn_bench()

    async def _fake_option_snapshot(self) -> dict[str, Any]:
        return {"status": "ok"}

    _patch_collection(monkeypatch, {"AAPL": {"sector": "Technology"}})
    monkeypatch.setattr(get_settings(), "option_signals_enabled", True)
    monkeypatch.setattr(data_agent_mod, "fetch_benchmark_history", _fake_market_benchmark)
    monkeypatch.setattr(data_agent_mod, "fetch_cn_sector_benchmark", _fake_cn_benchmark)
    monkeypatch.setattr(
        data_agent_mod.DataCollectionAgent, "_fetch_option_snapshot", _fake_option_snapshot
    )

    agent = data_agent_mod.DataCollectionAgent(name="data_collection")
    result = await agent.execute({"symbols": ["AAPL", "600000"]})

    # Two market indexes + one SPDR sector ETF — one benchmark round-trip
    # per represented market, one per mapped sector, exactly once each.
    assert sorted(fetched) == sorted(
        [data_agent_mod.BENCHMARK_TICKERS["us"], data_agent_mod.BENCHMARK_TICKERS["cn"], "XLK"]
    )

    us_block = result["market_data"]["AAPL"]
    assert us_block["benchmark_historical_data"]["symbol"] == data_agent_mod.BENCHMARK_TICKERS["us"]
    assert us_block["sector_benchmark_historical_data"]["symbol"] == "XLK"
    cn_block = result["market_data"]["600000"]
    assert cn_block["benchmark_historical_data"]["symbol"] == data_agent_mod.BENCHMARK_TICKERS["cn"]
    assert cn_block["sector_benchmark_historical_data"]["symbol"] == "银行"
    assert result["option_snapshot"] == {"status": "ok"}


async def test_us_only_run_skips_option_leg(monkeypatch: pytest.MonkeyPatch) -> None:
    """No CN symbols → no option snapshot: the leg never runs and the key
    stays absent (self-containment of the CN gate inside the gather)."""
    option_calls: list[str] = []

    async def _spy_option_snapshot(self) -> dict[str, Any]:
        option_calls.append("option")
        return {"status": "ok"}

    async def _fake_market_benchmark(ticker: str) -> dict[str, Any]:
        return _bench(ticker)

    async def _forbidden_cn(symbol: str) -> dict[str, Any]:
        raise AssertionError("CN industry benchmark must not run on US-only runs")

    _patch_collection(monkeypatch, {"AAPL": {"sector": "Technology"}})
    monkeypatch.setattr(get_settings(), "option_signals_enabled", True)
    monkeypatch.setattr(
        data_agent_mod.DataCollectionAgent, "_fetch_option_snapshot", _spy_option_snapshot
    )
    monkeypatch.setattr(data_agent_mod, "fetch_benchmark_history", _fake_market_benchmark)
    monkeypatch.setattr(data_agent_mod, "fetch_cn_sector_benchmark", _forbidden_cn)

    agent = data_agent_mod.DataCollectionAgent(name="data_collection")
    result = await agent.execute({"symbols": ["AAPL"]})

    assert option_calls == []
    assert "option_snapshot" not in result


async def test_disabled_toggle_skips_option_leg(monkeypatch: pytest.MonkeyPatch) -> None:
    """option_signals_enabled=False → the snapshot fetch never runs even
    with CN symbols present, and the key stays absent."""
    option_calls: list[str] = []

    async def _spy_option_snapshot(self) -> dict[str, Any]:
        option_calls.append("option")
        return {"status": "ok"}

    async def _fake_market_benchmark(ticker: str) -> dict[str, Any]:
        return _bench(ticker)

    async def _fake_cn_benchmark(symbol: str) -> dict[str, Any]:
        return _cn_bench()

    _patch_collection(monkeypatch, {})
    monkeypatch.setattr(get_settings(), "option_signals_enabled", False)
    monkeypatch.setattr(
        data_agent_mod.DataCollectionAgent, "_fetch_option_snapshot", _spy_option_snapshot
    )
    monkeypatch.setattr(data_agent_mod, "fetch_benchmark_history", _fake_market_benchmark)
    monkeypatch.setattr(data_agent_mod, "fetch_cn_sector_benchmark", _fake_cn_benchmark)

    agent = data_agent_mod.DataCollectionAgent(name="data_collection")
    result = await agent.execute({"symbols": ["600000"]})

    assert option_calls == []
    assert "option_snapshot" not in result
