"""Tencent kline fallback for the market benchmark indexes.

Production (Tencent Cloud host) verified 2026-09-28: yfinance has been 429
rate-limited for 3+ days, leaving both market benchmarks dark — CN
``000001.SS`` and US ``^GSPC`` — so beta/alpha/R²/correlation, the market
regime classification, and the sector benchmark degradation chain all lost
their regression input. Tencent's ifzq kline endpoint answers from the same
box; its contract traps are pinned here: kline rows are
``[date, open, close, high, low, volume]`` (close at index 2, NOT open at 1
or high at 3), and US codes requested as ``usINX`` answer under the dotted
response key ``us.INX``. Every scenario runs offline against faked HTTP and
faked yfinance modules; the local sandbox proxy poisons real-network tests.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pandas as pd
import pytest

import app.tools.data.fetcher as fetcher_mod
import app.tools.data.fetcher_benchmarks as fetcher_benchmarks_mod
import app.tools.data.tencent_benchmark as tencent_mod
from app.tools.data.fetcher import fetch_benchmark_history
from app.tools.data.provider_health import provider_health_snapshot, reset_provider_health
from app.tools.data.tencent_benchmark import tencent_index_history

# close values share no digit-pattern with their row's open/high/low — an
# index slip (1 or 3 instead of 2) cannot pass by coincidence.
_SH_ROWS = [
    ["2026-09-24", 3350.0, 3372.5, 3380.0, 3341.0, 38_000_000],
    ["2026-09-25", 3370.0, 3365.0, 3390.0, 3355.0, 36_000_000],
    ["2026-09-26", 3366.0, 3391.25, 3395.0, 3360.0, 40_000_000],
]
_SH_CLOSES = [3372.5, 3365.0, 3391.25]

_US_ROWS = [
    ["2026-09-24", 5700.0, 5718.2, 5725.0, 5690.0, 3_900_000_000],
    ["2026-09-25", 5715.0, 5698.4, 5720.0, 5691.0, 4_100_000_000],
]
_US_CLOSES = [5718.2, 5698.4]


class _FakeResponse:
    """requests.Response stand-in: status code + pre-parsed JSON payload."""

    def __init__(
        self,
        *,
        status_code: int = 200,
        payload: Any = None,
        json_error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error

    def json(self) -> Any:
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class _RecorderGet:
    """Stands in for requests.get; records every call's url/params/headers."""

    def __init__(self, *, response: Any = None, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._response = response
        self._error = error

    def __call__(self, url: str, **kwargs: Any) -> Any:
        self.calls.append({"url": url, **kwargs})
        if self._error is not None:
            raise self._error
        return self._response


def _kline_payload(code_key: str, rows: list, row_key: str = "day") -> dict[str, Any]:
    return {"code": 0, "data": {code_key: {row_key: rows}}}


@pytest.fixture(autouse=True)
def _clear_caches():
    fetcher_mod._cache.clear()
    yield
    fetcher_mod._cache.clear()


class TestTencentIndexHistory:
    def test_cn_index_maps_and_parses_close_at_index_two(self, monkeypatch) -> None:
        """sh000001 rows come back as the benchmark contract {symbol, dates,
        close} with close from column 2 — an index slip must fail loudly."""
        recorder = _RecorderGet(
            response=_FakeResponse(payload=_kline_payload("sh000001", _SH_ROWS))
        )
        monkeypatch.setattr(tencent_mod.requests, "get", recorder)

        result = tencent_index_history("000001.SS")

        assert result == {
            "symbol": "000001.SS",
            "dates": ["2026-09-24", "2026-09-25", "2026-09-26"],
            "close": _SH_CLOSES,
        }

    def test_us_index_answers_under_dotted_key(self, monkeypatch) -> None:
        """Requesting usINX, the response nests rows under 'us.INX' (dot
        form) — the parser must tolerate both spellings."""
        recorder = _RecorderGet(response=_FakeResponse(payload=_kline_payload("us.INX", _US_ROWS)))
        monkeypatch.setattr(tencent_mod.requests, "get", recorder)

        result = tencent_index_history("^GSPC")

        assert result is not None
        assert result["symbol"] == "^GSPC"
        assert result["close"] == _US_CLOSES
        assert result["dates"] == ["2026-09-24", "2026-09-25"]

    def test_us_index_under_plain_key_also_accepted(self, monkeypatch) -> None:
        """The same request may answer under the plain 'usINX' key."""
        recorder = _RecorderGet(response=_FakeResponse(payload=_kline_payload("usINX", _US_ROWS)))
        monkeypatch.setattr(tencent_mod.requests, "get", recorder)

        assert (tencent_index_history("^GSPC") or {}).get("close") == _US_CLOSES

    def test_qfqday_rows_accepted(self, monkeypatch) -> None:
        """The endpoint sometimes nests rows under 'qfqday' instead of 'day'."""
        recorder = _RecorderGet(
            response=_FakeResponse(payload=_kline_payload("sh000001", _SH_ROWS, row_key="qfqday"))
        )
        monkeypatch.setattr(tencent_mod.requests, "get", recorder)

        assert (tencent_index_history("000001.SS") or {}).get("close") == _SH_CLOSES

    def test_request_shape_code_count_timeout_and_ua(self, monkeypatch) -> None:
        """One GET to the kline endpoint: param '<code>,day,,,800' (the 2y
        benchmark window ≈ 490 bars, with truncation headroom), a browser
        UA, and a bounded timeout."""
        recorder = _RecorderGet(
            response=_FakeResponse(payload=_kline_payload("sh000001", _SH_ROWS))
        )
        monkeypatch.setattr(tencent_mod.requests, "get", recorder)

        tencent_index_history("000001.SS")

        call = recorder.calls[0]
        assert call["url"] == "https://web.ifzq.gtimg.cn/appstock/app/kline/kline"
        assert call["params"] == {"param": "sh000001,day,,,800"}
        assert "Mozilla" in call["headers"]["User-Agent"]
        assert call["timeout"] == 15

    def test_http_non_200_returns_none(self, monkeypatch) -> None:
        recorder = _RecorderGet(response=_FakeResponse(status_code=500, payload={}))
        monkeypatch.setattr(tencent_mod.requests, "get", recorder)

        assert tencent_index_history("000001.SS") is None

    def test_malformed_json_returns_none(self, monkeypatch) -> None:
        recorder = _RecorderGet(response=_FakeResponse(json_error=ValueError("Expecting value")))
        monkeypatch.setattr(tencent_mod.requests, "get", recorder)

        assert tencent_index_history("^GSPC") is None

    def test_rows_empty_returns_none(self, monkeypatch) -> None:
        recorder = _RecorderGet(response=_FakeResponse(payload=_kline_payload("sh000001", [])))
        monkeypatch.setattr(tencent_mod.requests, "get", recorder)

        assert tencent_index_history("000001.SS") is None

    def test_unparsable_date_returns_none(self, monkeypatch) -> None:
        """A compact-date row (20260914) breaks the %Y-%m-%d contract the
        aligned-returns join keys on — the whole response is untrusted."""
        rows = [["20260914", 3350.0, 3372.5, 3380.0, 3341.0, 38_000_000]]
        recorder = _RecorderGet(response=_FakeResponse(payload=_kline_payload("sh000001", rows)))
        monkeypatch.setattr(tencent_mod.requests, "get", recorder)

        assert tencent_index_history("000001.SS") is None

    def test_non_numeric_close_returns_none(self, monkeypatch) -> None:
        rows = [["2026-09-24", 3350.0, "n/a", 3380.0, 3341.0, 38_000_000]]
        recorder = _RecorderGet(response=_FakeResponse(payload=_kline_payload("sh000001", rows)))
        monkeypatch.setattr(tencent_mod.requests, "get", recorder)

        assert tencent_index_history("000001.SS") is None

    def test_short_row_returns_none(self, monkeypatch) -> None:
        rows = [["2026-09-24", 3350.0, 3372.5]]
        recorder = _RecorderGet(response=_FakeResponse(payload=_kline_payload("sh000001", rows)))
        monkeypatch.setattr(tencent_mod.requests, "get", recorder)

        assert tencent_index_history("000001.SS") is None

    def test_unmapped_symbol_returns_none_without_http(self, monkeypatch) -> None:
        """Only the two market indexes are in scope — anything else (sector
        ETFs included) fails fast with no request."""
        recorder = _RecorderGet(response=_FakeResponse(payload={}))
        monkeypatch.setattr(tencent_mod.requests, "get", recorder)

        assert tencent_index_history("XLK") is None
        assert tencent_index_history("600519") is None
        assert recorder.calls == []

    def test_request_exception_returns_none(self, monkeypatch) -> None:
        """Timeout/connection errors must degrade to None, never raise."""
        recorder = _RecorderGet(error=TimeoutError("connect timed out"))
        monkeypatch.setattr(tencent_mod.requests, "get", recorder)

        assert tencent_index_history("000001.SS") is None


class _RateLimitedYf:
    """The documented production state (429 for 3+ days): every Ticker call
    raises before any frame exists."""

    @staticmethod
    def Ticker(symbol: str):  # noqa: N802 - yfinance API shape
        raise RuntimeError("Too Many Requests.")


class _EmptyYf:
    """yfinance answers but the rate-limited query yields an empty frame."""

    @staticmethod
    def Ticker(symbol: str):  # noqa: N802 - yfinance API shape
        return types.SimpleNamespace(history=lambda **kw: pd.DataFrame())


class _HealthyYf:
    @staticmethod
    def Ticker(symbol: str):  # noqa: N802 - yfinance API shape
        index = [pd.Timestamp("2026-09-25"), pd.Timestamp("2026-09-26")]
        return types.SimpleNamespace(
            history=lambda **kw: pd.DataFrame({"Close": [4190.0, 4195.5]}, index=index)
        )


def _install_yf(monkeypatch: pytest.MonkeyPatch, ticker: Any) -> None:
    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=ticker))


class TestBenchmarkFallbackWiring:
    @pytest.mark.asyncio
    async def test_rate_limited_yfinance_falls_back_to_tencent(self, monkeypatch) -> None:
        """The production failure shape: yfinance raises, Tencent answers —
        the caller sees the same {symbol, dates, close} contract, symbol
        still in yahoo form so benchmark lookups keep keying on it."""
        _install_yf(monkeypatch, _RateLimitedYf.Ticker)
        recorder = _RecorderGet(
            response=_FakeResponse(payload=_kline_payload("sh000001", _SH_ROWS))
        )
        monkeypatch.setattr(tencent_mod.requests, "get", recorder)

        result = await fetch_benchmark_history("000001.SS")

        assert result == {
            "symbol": "000001.SS",
            "dates": ["2026-09-24", "2026-09-25", "2026-09-26"],
            "close": _SH_CLOSES,
        }
        assert len(recorder.calls) == 1

    @pytest.mark.asyncio
    async def test_empty_yfinance_history_falls_back_to_tencent(self, monkeypatch) -> None:
        """yfinance answering with an empty frame is just as blind — the
        fallback must trigger on the empty result too, not only on raises."""
        _install_yf(monkeypatch, _EmptyYf.Ticker)
        recorder = _RecorderGet(response=_FakeResponse(payload=_kline_payload("us.INX", _US_ROWS)))
        monkeypatch.setattr(tencent_mod.requests, "get", recorder)

        result = await fetch_benchmark_history("^GSPC")

        assert result is not None
        assert result["symbol"] == "^GSPC"
        assert result["close"] == _US_CLOSES

    @pytest.mark.asyncio
    async def test_fallback_result_is_cached_like_a_success(self, monkeypatch) -> None:
        """A Tencent-sourced benchmark flows through the success-cache
        semantics: one HTTP fetch serves repeated calls for 30 minutes."""
        _install_yf(monkeypatch, _RateLimitedYf.Ticker)
        recorder = _RecorderGet(
            response=_FakeResponse(payload=_kline_payload("sh000001", _SH_ROWS))
        )
        monkeypatch.setattr(tencent_mod.requests, "get", recorder)

        first = await fetch_benchmark_history("000001.SS")
        second = await fetch_benchmark_history("000001.SS")

        assert second == first
        assert len(recorder.calls) == 1

    @pytest.mark.asyncio
    async def test_healthy_yfinance_bit_for_bit_unchanged(self, monkeypatch) -> None:
        """yfinance healthy means the fallback must not even be attempted —
        the result is yfinance's own dates/closes, unchanged."""
        _install_yf(monkeypatch, _HealthyYf.Ticker)

        def _must_not_run(*args: Any, **kwargs: Any):
            raise AssertionError("tencent fallback must not run when yfinance is healthy")

        monkeypatch.setattr(tencent_mod.requests, "get", _must_not_run)

        result = await fetch_benchmark_history("^GSPC")

        assert result == {
            "symbol": "^GSPC",
            "dates": ["2026-09-25", "2026-09-26"],
            "close": [4190.0, 4195.5],
        }

    @pytest.mark.asyncio
    async def test_both_sources_fail_returns_none_uncached(self, monkeypatch) -> None:
        """Tencent failing too must keep the existing None semantics AND the
        failure-not-cached contract — the next call retries both sources."""
        _install_yf(monkeypatch, _RateLimitedYf.Ticker)
        recorder = _RecorderGet(response=_FakeResponse(status_code=503, payload={}))
        monkeypatch.setattr(tencent_mod.requests, "get", recorder)

        assert await fetch_benchmark_history("000001.SS") is None
        assert not any(key.startswith("bench_") for key in fetcher_mod._cache)

        # Not poisoned: the retry re-attempts the fallback source.
        assert await fetch_benchmark_history("000001.SS") is None
        assert len(recorder.calls) == 2


class _FakeSina:
    """Recorder for the async ``_sina_us_hist`` seam: returns a fixed
    history dict (or None) and records every (symbol, period) call."""

    def __init__(self, hist: dict[str, Any] | None) -> None:
        self.hist = hist
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, symbol: str, period: str = "3y") -> dict[str, Any] | None:
        self.calls.append((symbol, period))
        return self.hist


_SINA_HIST = {
    "dates": ["2026-09-25", "2026-09-26"],
    "open": [52.0, 52.5],
    "high": [53.0, 54.0],
    "low": [51.5, 52.2],
    "close": [52.8, 53.6],
    "volume": [9_000_000, 8_500_000],
}


class TestSectorEtfSinaFallback:
    """The benchmark chain's third leg, sector ETFs only.

    Probed 2026-09-29: Tencent's ifzq kline serves full history for indexes
    (usINX 801 rows) but exactly ONE row for US ETFs at any count — the
    SPDR tickers have no viable Tencent fallback by endpoint design. When
    yfinance is dark (the production host's documented state), US
    sector_relative was left without regression input. Sina's US daily
    serves full SPDR history (XLF verified: 6,471 rows back to 2001) and is
    the one US history source answering from the production host
    (iteration 91). Every test runs offline against the fakes above.
    """

    @pytest.mark.asyncio
    async def test_rate_limited_yfinance_falls_back_to_sina_for_etfs(self, monkeypatch) -> None:
        """The production failure shape for sector ETFs: yfinance raises,
        tencent has no ETF mapping (returns None, no HTTP), Sina answers —
        the caller gets the same {symbol, dates, close} contract with the
        yahoo-form symbol preserved."""
        _install_yf(monkeypatch, _RateLimitedYf.Ticker)
        sina = _FakeSina(_SINA_HIST)
        monkeypatch.setattr(fetcher_benchmarks_mod, "_sina_us_hist", sina)

        result = await fetch_benchmark_history("XLF")

        assert result == {
            "symbol": "XLF",
            "dates": ["2026-09-25", "2026-09-26"],
            "close": [52.8, 53.6],
        }
        # The benchmark window (2y), not the default 3y stock-history window.
        assert sina.calls == [("XLF", "2y")]

    @pytest.mark.asyncio
    async def test_healthy_yfinance_never_touches_sina(self, monkeypatch) -> None:
        """yfinance healthy means the third leg must not even be attempted —
        the result is yfinance's own dates/closes, unchanged."""
        _install_yf(monkeypatch, _HealthyYf.Ticker)
        sina = _FakeSina(_SINA_HIST)
        monkeypatch.setattr(fetcher_benchmarks_mod, "_sina_us_hist", sina)

        result = await fetch_benchmark_history("XLF")

        assert result == {
            "symbol": "XLF",
            "dates": ["2026-09-25", "2026-09-26"],
            "close": [4190.0, 4195.5],
        }
        assert sina.calls == []

    @pytest.mark.asyncio
    async def test_market_indexes_never_touch_sina(self, monkeypatch) -> None:
        """The Sina leg exists for sector ETFs; the market indexes keep the
        two-leg chain (^GSPC is tencent-mapped) even when both legs are
        dark — None stays None without a third attempt."""
        _install_yf(monkeypatch, _RateLimitedYf.Ticker)
        recorder = _RecorderGet(response=_FakeResponse(status_code=503, payload={}))
        monkeypatch.setattr(tencent_mod.requests, "get", recorder)
        sina = _FakeSina(_SINA_HIST)
        monkeypatch.setattr(fetcher_benchmarks_mod, "_sina_us_hist", sina)

        assert await fetch_benchmark_history("^GSPC") is None
        assert sina.calls == []
        assert len(recorder.calls) == 1

    @pytest.mark.asyncio
    async def test_sina_failure_returns_none_and_records_fail(self, monkeypatch) -> None:
        """Sina failing too keeps the None + fail-uncached contract, and the
        provider-health snapshot shows the third leg honestly failing."""
        _install_yf(monkeypatch, _RateLimitedYf.Ticker)
        sina = _FakeSina(None)
        monkeypatch.setattr(fetcher_benchmarks_mod, "_sina_us_hist", sina)
        reset_provider_health()

        assert await fetch_benchmark_history("XLF") is None
        assert not any(key.startswith("bench_") for key in fetcher_mod._cache)

        stats = provider_health_snapshot()["providers"].get("sina-benchmark")
        assert stats is not None
        assert stats["fail"] == 1

        # Not poisoned: the retry re-attempts the Sina leg.
        assert await fetch_benchmark_history("XLF") is None
        assert len(sina.calls) == 2

    @pytest.mark.asyncio
    async def test_sina_success_is_cached_and_records_ok(self, monkeypatch) -> None:
        """A Sina-sourced benchmark flows through the success-cache
        semantics (one fetch serves repeated calls) and the provider-health
        snapshot records the ok outcome."""
        _install_yf(monkeypatch, _RateLimitedYf.Ticker)
        sina = _FakeSina(_SINA_HIST)
        monkeypatch.setattr(fetcher_benchmarks_mod, "_sina_us_hist", sina)
        reset_provider_health()

        first = await fetch_benchmark_history("XLF")
        second = await fetch_benchmark_history("XLF")

        assert second == first
        assert len(sina.calls) == 1
        stats = provider_health_snapshot()["providers"].get("sina-benchmark")
        assert stats is not None
        assert stats["ok"] == 1
