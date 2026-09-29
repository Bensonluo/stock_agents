"""Risk correctness specifications for the symbol-only analysis tool."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
import pytest

from app.config import get_settings
from app.tools.analysis import auto_tools


def _history(returns: np.ndarray) -> dict[str, list]:
    prices = [100.0]
    for value in returns:
        prices.append(prices[-1] * (1 + float(value)))
    dates = [(date(2024, 1, 1) + timedelta(days=index)).isoformat() for index in range(len(prices))]
    return {"dates": dates, "close": prices}


def _qvix_stub() -> dict[str, Any]:
    # 90th percentile of the 1-year QVIX range → 恐慌 (panic) band.
    return {"current": 25.0, "as_of": "2026-09-29", "percentile_1y": 0.9, "history_days": 500}


def _fake_fetch_with(market: dict[str, Any]):
    async def fake_fetch(symbol: str) -> dict:
        return {"market_data": {symbol: market}, "financial_data": {}, "news_data": []}

    return fake_fetch


def _patch_option_seams(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: dict[str, Any] | None,
    qvix: dict[str, Any] | None,
    calls: list[str] | None = None,
) -> None:
    def _sse() -> dict[str, Any] | None:
        if calls is not None:
            calls.append("sse")
        return snapshot

    def _qvix(store: Any) -> dict[str, Any] | None:
        if calls is not None:
            calls.append("qvix")
        return qvix

    monkeypatch.setattr(auto_tools, "fetch_sse_option_snapshot", _sse)
    monkeypatch.setattr(auto_tools, "fetch_qvix_context", _qvix)


@pytest.mark.asyncio
async def test_symbol_only_tool_does_not_fabricate_beta_or_position(monkeypatch) -> None:
    async def fake_fetch(symbol: str) -> dict:
        return {
            "market_data": {
                symbol: {
                    "symbol": symbol,
                    "historical_data": _history(np.linspace(-0.02, 0.025, 24)),
                }
            },
            "financial_data": {},
            "news_data": [],
        }

    monkeypatch.setattr(auto_tools, "_fetch_and_split", fake_fetch)

    result = await auto_tools.assess_risk.ainvoke({"symbol": "TEST"})

    # Flat multi-symbol shell (iteration 156): the per-symbol entry lives
    # under the symbol key so run-level annotations can ride along.
    assert result["TEST"]["metrics"]["beta"] is None
    assert result["TEST"]["metrics"]["beta_status"] == "insufficient_data"
    assert result["TEST"]["risk_score_status"] == "partial"
    assert result["TEST"]["position_recommendation"]["max_position_size"] is None


@pytest.mark.asyncio
async def test_fetch_and_split_attaches_benchmark(monkeypatch) -> None:
    async def fake_snapshot(symbol: str) -> dict:
        return {
            "market_data": {
                symbol: {
                    "symbol": symbol,
                    "current_price": 10.0,
                    "historical_data": _history(np.linspace(-0.01, 0.01, 30)),
                }
            },
            "financial_data": {},
            "news_data": [],
        }

    async def fake_bench(ticker: str) -> dict:
        return {"symbol": ticker, "dates": ["2024-01-01"], "close": [4000.0]}

    monkeypatch.setattr(auto_tools, "fetch_stock_data", fake_snapshot)
    monkeypatch.setattr(auto_tools, "fetch_benchmark_history", fake_bench)

    data = await auto_tools._fetch_and_split("TEST")

    assert data["market_data"]["TEST"]["benchmark_historical_data"]["symbol"] == "^GSPC"


@pytest.mark.asyncio
async def test_tool_output_is_the_canonical_assess_symbol_block(monkeypatch) -> None:
    market = {
        "symbol": "TEST",
        "historical_data": _history(np.linspace(-0.02, 0.025, 60)),
        "benchmark_historical_data": _history(np.linspace(-0.01, 0.015, 60)),
    }

    monkeypatch.setattr(auto_tools, "_fetch_and_split", _fake_fetch_with(market))

    from app.tools.risk.assessment import assess_symbol

    result = await auto_tools.assess_risk.ainvoke({"symbol": "TEST"})

    # Bit-for-bit parity with the engine path the pipeline risk agent uses.
    assert result["TEST"] == assess_symbol("TEST", market)
    # The canonical block carries guarded VaR + CVaR + live beta — the old
    # inline copy lacked the >=20-return guard and CVaR entirely.
    assert result["TEST"]["metrics"]["cvar_95"] is not None
    assert result["TEST"]["metrics"]["beta"] is not None
    assert result["TEST"]["risk_score_status"] == "complete"


@pytest.mark.asyncio
async def test_tool_parks_market_regime_beside_symbol_entry(monkeypatch) -> None:
    # Alternating -1.0%/-0.2% steps ×125 → 250 returns / 251 closes: real
    # dispersion (a constant-rate tape is zero-variance and the classifier
    # refuses it) and a steady slide far under the SMA-200 → trend "bear".
    market = {
        "symbol": "TEST",
        "historical_data": _history(np.linspace(-0.02, 0.025, 60)),
        "benchmark_historical_data": _history(np.tile([-0.010, -0.002], 125)),
    }

    monkeypatch.setattr(auto_tools, "_fetch_and_split", _fake_fetch_with(market))

    result = await auto_tools.assess_risk.ainvoke({"symbol": "TEST"})

    assert result["TEST"]["risk_score"] is not None
    assert result["market_regime"]["status"] == "ok"
    assert result["market_regime"]["trend"] == "bear"


@pytest.mark.asyncio
async def test_tool_omits_regime_without_benchmark(monkeypatch) -> None:
    market = {"symbol": "TEST", "historical_data": _history(np.linspace(-0.02, 0.025, 60))}

    monkeypatch.setattr(auto_tools, "_fetch_and_split", _fake_fetch_with(market))

    result = await auto_tools.assess_risk.ainvoke({"symbol": "TEST"})

    # Degraded run: no benchmark → no fabricated regime.
    assert "market_regime" not in result


@pytest.mark.asyncio
async def test_tool_parks_option_implied_for_cn_symbols(monkeypatch) -> None:
    market = {"symbol": "600000", "historical_data": _history(np.linspace(-0.02, 0.025, 60))}

    monkeypatch.setattr(auto_tools, "_fetch_and_split", _fake_fetch_with(market))
    monkeypatch.setattr(get_settings(), "option_signals_enabled", True)
    _patch_option_seams(
        monkeypatch,
        snapshot={"contracts": None, "pcr_by_underlying": None},
        qvix=_qvix_stub(),
    )

    result = await auto_tools.assess_risk.ainvoke({"symbol": "600000"})

    assert result["600000"]["risk_score"] is not None
    assert result["option_implied"]["status"] == "ok"
    assert result["option_implied"]["regime"] == "恐慌"


@pytest.mark.asyncio
async def test_tool_omits_option_implied_for_us_symbols(monkeypatch) -> None:
    market = {"symbol": "AAPL", "historical_data": _history(np.linspace(-0.02, 0.025, 60))}

    monkeypatch.setattr(auto_tools, "_fetch_and_split", _fake_fetch_with(market))
    fetch_calls: list[str] = []
    _patch_option_seams(monkeypatch, snapshot=None, qvix=None, calls=fetch_calls)

    result = await auto_tools.assess_risk.ainvoke({"symbol": "AAPL"})

    # The CN gate must prevent the fetch from ever being attempted.
    assert fetch_calls == []
    assert "option_implied" not in result


@pytest.mark.asyncio
async def test_tool_omits_option_implied_when_toggle_off(monkeypatch) -> None:
    market = {"symbol": "600000", "historical_data": _history(np.linspace(-0.02, 0.025, 60))}

    monkeypatch.setattr(auto_tools, "_fetch_and_split", _fake_fetch_with(market))
    monkeypatch.setattr(get_settings(), "option_signals_enabled", False)
    fetch_calls: list[str] = []
    _patch_option_seams(monkeypatch, snapshot=None, qvix=None, calls=fetch_calls)

    result = await auto_tools.assess_risk.ainvoke({"symbol": "600000"})

    assert fetch_calls == []
    assert "option_implied" not in result


@pytest.mark.asyncio
async def test_tool_omits_option_implied_when_fetch_fails(monkeypatch) -> None:
    market = {"symbol": "600000", "historical_data": _history(np.linspace(-0.02, 0.025, 60))}

    monkeypatch.setattr(auto_tools, "_fetch_and_split", _fake_fetch_with(market))
    monkeypatch.setattr(get_settings(), "option_signals_enabled", True)
    _patch_option_seams(monkeypatch, snapshot=None, qvix=None)

    result = await auto_tools.assess_risk.ainvoke({"symbol": "600000"})

    # Both seams degraded → key absent, never an error shell mid-run.
    assert "option_implied" not in result


@pytest.mark.asyncio
async def test_annotation_blocks_never_touch_the_symbol_score(monkeypatch) -> None:
    # Identical tape as stock AND benchmark → beta exactly 1.0, which adds
    # nothing under the higher-is-riskier semantics — so the score must be
    # bit-identical with or without the annotation blocks attached.
    tape = _history(np.tile([-0.010, -0.002], 125))
    plain = {"symbol": "600000", "historical_data": tape}
    annotated = {
        "symbol": "600000",
        "historical_data": tape,
        "benchmark_historical_data": tape,
    }

    monkeypatch.setattr(get_settings(), "option_signals_enabled", True)
    monkeypatch.setattr(auto_tools, "_fetch_and_split", _fake_fetch_with(plain))
    _patch_option_seams(monkeypatch, snapshot=None, qvix=None)
    bare = await auto_tools.assess_risk.ainvoke({"symbol": "600000"})

    monkeypatch.setattr(auto_tools, "_fetch_and_split", _fake_fetch_with(annotated))
    _patch_option_seams(
        monkeypatch,
        snapshot={"contracts": None, "pcr_by_underlying": None},
        qvix=_qvix_stub(),
    )
    full = await auto_tools.assess_risk.ainvoke({"symbol": "600000"})

    assert bare["600000"]["risk_score"] == full["600000"]["risk_score"]
    # The blocks were actually present in the annotated run (the purity
    # comparison above is between annotated and unannotated, not two holes).
    assert "market_regime" not in bare
    assert "option_implied" not in bare
    assert full["market_regime"]["status"] == "ok"
    assert full["option_implied"]["status"] == "ok"
