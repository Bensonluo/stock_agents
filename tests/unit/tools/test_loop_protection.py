"""Tests for the fetch-failure circuit-breaker and rotation loop detection."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import app.tools.analysis.auto_tools as auto_tools
from app.tools.analysis.auto_tools import (
    _fetch_failures,
    _fetch_failures_exceeded,
    _record_fetch_failure,
    _reset_fetch_failures,
    data_unavailable_error,
)


@pytest.fixture(autouse=True)
def clean_memo():
    _fetch_failures.clear()
    yield
    _fetch_failures.clear()


class TestHkSymbols:
    def test_hk_detection_and_normalization(self) -> None:
        from app.tools.data.fetcher import (
            _convert_to_yahoo_symbol,
            _hk_akshare_code,
            _hk_code,
            _is_hk_symbol,
        )

        for variant in ("0700.HK", "00700.HK", "0700", "00700"):
            assert _is_hk_symbol(variant), variant
        for non_hk in ("AAPL", "600519", "3690", "TSLA"):
            assert not _is_hk_symbol(non_hk), non_hk
        assert _hk_code("00700.HK") == "0700"
        assert _convert_to_yahoo_symbol("00700") == "0700.HK"
        assert _hk_akshare_code("0700.HK") == "00700"

    @pytest.mark.asyncio
    async def test_akshare_hk_snapshot_builds_market_block(self) -> None:
        import pandas as pd

        from app.tools.data.fetcher import _akshare_hk

        days = 30
        closes = [300.0 + i for i in range(days)]
        index = pd.bdate_range("2026-07-01", periods=days)
        fake_df = pd.DataFrame(
            {
                "日期": index.strftime("%Y-%m-%d"),
                "开盘": closes, "收盘": closes, "最高": closes, "最低": closes,
                "成交量": [1e6] * days,
            }
        )

        class FakeAk:
            @staticmethod
            def stock_hk_hist(**kwargs):
                assert kwargs["symbol"] == "00700"
                return fake_df

        result = await _akshare_hk("0700.HK", FakeAk())
        mkt = result["market_data"]["0700.HK"]
        assert mkt["current_price"] == closes[-1]
        assert mkt["previous_close"] == closes[-2]
        assert mkt["historical_data"]["close"] == closes
        assert result["provider"] == "akshare-hk"


class TestFailureCircuitBreaker:
    def test_error_is_instructive(self) -> None:
        _record_fetch_failure("TEST")
        _record_fetch_failure("TEST")

        err = data_unavailable_error("TEST")
        assert err["data_available"] is False
        assert "generate_report" in err["error"]
        assert "勿再调用" in err["error"] or "请勿再调用" in err["error"]

    def test_breaker_opens_after_two_failures(self) -> None:
        _record_fetch_failure("TEST")
        assert not _fetch_failures_exceeded("TEST")
        _record_fetch_failure("TEST")
        assert _fetch_failures_exceeded("TEST")

    def test_reset_on_success(self) -> None:
        _record_fetch_failure("TEST")
        _record_fetch_failure("TEST")
        _reset_fetch_failures("TEST")
        assert not _fetch_failures_exceeded("TEST")

    @pytest.mark.asyncio
    async def test_third_fetch_never_hits_providers(self) -> None:
        """After 2 failures the 3rd call short-circuits without any provider."""
        _record_fetch_failure("0700.HK")
        _record_fetch_failure("0700.HK")

        async def boom(*a, **k):  # provider chain would raise if called
            raise AssertionError("provider chain must not be reached")

        with patch.object(auto_tools, "fetch_stock_data", boom), \
             patch.object(auto_tools, "fetch_historical", boom):
            result = await auto_tools._fetch_and_split("0700.HK")

        assert result["data_available"] is False
        assert "generate_report" in result["error"]

    @pytest.mark.asyncio
    async def test_raw_fetch_tool_also_short_circuits(self) -> None:
        from app.tools.data import market_data as md

        _record_fetch_failure("0700.HK")
        _record_fetch_failure("0700.HK")

        async def boom(*a, **k):
            raise AssertionError("providers must not be reached")

        with patch.object(md, "fetch_stock_data_from_providers", boom):
            result = await md.fetch_stock_data_tool.ainvoke({"symbols": ["0700.HK"]})

        assert result["data_available"] is False


class TestRotationLoopDetection:
    def _reflect(self, messages):
        """Load reflect_node via stub loader and run it."""
        import importlib.util
        import sys
        from pathlib import Path
        from types import ModuleType

        base = ModuleType("app.agents.base")
        base.BaseAgent = type("BaseAgent", (), {})
        base.StatelessAgent = type("StatelessAgent", (), {})
        st = ModuleType("app.orchestration.state")
        st.AgentState = dict
        replaced = {n: sys.modules.get(n) for n in ("app.agents.base", "app.orchestration.state")}
        sys.modules.update({"app.agents.base": base, "app.orchestration.state": st})
        try:
            path = Path(__file__).parents[3] / "app" / "react_agent" / "react_agent.py"
            spec = importlib.util.spec_from_file_location("react_loop_test", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.reflect_node({"messages": messages, "iteration": 3, "max_iterations": 15})
        finally:
            for n, o in replaced.items():
                if o is None:
                    sys.modules.pop(n, None)
                else:
                    sys.modules[n] = o

    @staticmethod
    def _ai_with_calls(calls):
        from langchain_core.messages import AIMessage

        return AIMessage(content="", tool_calls=[
            {"name": n, "args": a, "id": f"c{i}"} for i, (n, a) in enumerate(calls)
        ])

    def test_rotation_loop_forces_finish(self) -> None:
        call = ("fetch_stock_data_tool", {"symbols": ["0700.HK"]})
        messages = [self._ai_with_calls([call]) for _ in range(3)]

        result = self._reflect(messages)

        assert "STOP calling tools" in result["messages"][0].content
        assert "generate_report" in result["messages"][0].content

    def test_symbol_variant_rotation_also_caught(self) -> None:
        """The live failure: same tool, rotating argument spellings."""
        calls = [
            ("fetch_stock_data_tool", {"symbols": ["0700.HK"]}),
            ("get_stock_overview", {"symbol": "0700.HK"}),
            ("analyze_fundamental", {"symbol": "0700.HK"}),
            ("fetch_stock_data_tool", {"symbols": ["0700.HK"]}),
            ("get_stock_overview", {"symbol": "0700.HK"}),
            ("analyze_fundamental", {"symbol": "0700.HK"}),
            ("fetch_stock_data_tool", {"symbols": ["0700.HK"]}),
        ]
        messages = [self._ai_with_calls(calls[i:i+3]) for i in range(0, len(calls), 3)]

        result = self._reflect(messages)

        assert "STOP calling tools" in result["messages"][0].content

    def test_normal_progress_not_interrupted(self) -> None:
        calls = [
            ("fetch_stock_data_tool", {"symbols": ["AAPL"]}),
            ("analyze_technical", {"symbol": "AAPL"}),
            ("analyze_fundamental", {"symbol": "AAPL"}),
            ("assess_risk", {"symbol": "AAPL"}),
        ]
        messages = [self._ai_with_calls(calls[:2]), self._ai_with_calls(calls[2:])]

        result = self._reflect(messages)

        assert not any("STOP calling tools" in getattr(m, "content", "") for m in result.get("messages", []))
