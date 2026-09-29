"""SSE options implied-signal layer: pure metrics + offline fetch seams.

Pins the iteration-155 contracts: the degenerate-row filter and
hand-calculated ATM/term-structure/skew values from a two-expiry fixture,
the official PCR aggregation, the QVIX percentile regime label, and the
fetch seams driven offline through a fake akshare module (walkback, join,
partial degradation, provider-health outcomes, local-store fallback).
"""

from __future__ import annotations

import sys
import types
from datetime import date, timedelta
from typing import Any

import pandas as pd
import pytest

from app.tools.data import fetcher_common
from app.tools.data.option_signals import (
    build_option_implied,
    compute_iv_metrics,
    compute_pcr,
    fetch_qvix_context,
    fetch_sse_option_snapshot,
)
from app.tools.data.provider_health import provider_health_snapshot, reset_provider_health
from app.tools.data.qvix_store import QvixStore

NEAR = "2026-10-28"
NEXT = "2026-11-25"


# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------


def _contract(
    strike: float,
    delta: float,
    iv: float,
    cp: str = "C",
    expire: str = NEAR,
    symbol: str = "510050",
) -> dict[str, Any]:
    return {
        "contract_id": f"{cp}{strike}{expire}",
        "symbol": symbol,
        "cp": cp,
        "strike": strike,
        "expire_date": expire,
        "delta": delta,
        "iv": iv,
    }


def _two_expiry_contracts() -> list[dict[str, Any]]:
    """Hand-calculated surface (values pinned in the assertions below).

    Near expiry ATM call: strike 3.00 / |delta| 0.50 / IV 0.185.
    Next expiry ATM call: strike 3.00 / |delta| 0.48 / IV 0.210.
    Near put band (-0.35..-0.15): IVs 0.175, 0.210 → mean 0.1925.
    Near call band (0.15..0.35): IVs 0.160, 0.150 → mean 0.155.
    """
    return [
        # near expiry, calls
        _contract(2.80, 0.80, 0.220),
        _contract(2.90, 0.60, 0.200),
        _contract(3.00, 0.50, 0.185),
        _contract(3.10, 0.30, 0.160),
        _contract(3.20, 0.25, 0.150),
        _contract(3.30, 0.10, 0.140),
        # near expiry, puts
        _contract(2.80, -0.20, 0.175, cp="P"),
        _contract(2.90, -0.30, 0.210, cp="P"),
        _contract(3.00, -0.45, 0.240, cp="P"),
        _contract(2.70, -0.10, 0.160, cp="P"),
        # next expiry
        _contract(3.00, 0.48, 0.210, expire=NEXT),
        _contract(3.10, 0.32, 0.180, expire=NEXT),
        _contract(2.90, 0.62, 0.250, expire=NEXT),
        _contract(2.90, -0.28, 0.230, cp="P", expire=NEXT),
        _contract(3.00, -0.42, 0.260, cp="P", expire=NEXT),
    ]


@pytest.fixture(autouse=True)
def _clean_state():
    """Global caches + provider counters must not leak between tests."""
    reset_provider_health()
    for key in ("option_snapshot", "qvix_context"):
        fetcher_common._cache.pop(key, None)
    yield
    reset_provider_health()
    for key in ("option_snapshot", "qvix_context"):
        fetcher_common._cache.pop(key, None)


@pytest.fixture()
def store(tmp_path) -> QvixStore:
    return QvixStore(db_path=tmp_path / "qvix_test.db")


def _risk_frame(trade_date: str, rows: list[tuple[str, str, float, float]]) -> pd.DataFrame:
    """option_risk_indicator_sse shape: (CONTRACT_ID, CONTRACT_SYMBOL, delta, iv)."""
    return pd.DataFrame(
        {
            "TRADE_DATE": [trade_date] * len(rows),
            "SECURITY_ID": [f"SID{i}" for i in range(len(rows))],
            "CONTRACT_ID": [r[0] for r in rows],
            "CONTRACT_SYMBOL": [r[1] for r in rows],
            "DELTA_VALUE": [r[2] for r in rows],
            "THETA_VALUE": [-0.001] * len(rows),
            "GAMMA_VALUE": [0.5] * len(rows),
            "VEGA_VALUE": [0.002] * len(rows),
            "RHO_VALUE": [0.01] * len(rows),
            "IMPLC_VOLATLTY": [r[3] for r in rows],
        }
    )


def _dir_frame(rows: list[tuple[str, str, str, str, float, str]]) -> pd.DataFrame:
    """option_current_day_sse shape: (code, CONTRACT_ID, name, underlying, cp_label, strike, expire)."""
    return pd.DataFrame(
        {
            "合约编码": [r[0] for r in rows],
            "合约交易代码": [r[1] for r in rows],
            "合约简称": [r[2] for r in rows],
            "标的券名称及代码": [r[3] for r in rows],
            "类型": [r[4] for r in rows],
            "行权价": [r[5] for r in rows],
            "合约单位": [10000] * len(rows),
            "期权行权日": ["2026-09-24"] * len(rows),
            "行权交收日": ["2026-09-25"] * len(rows),
            "到期日": [r[6] for r in rows],
            "开始日期": ["2026-06-01"] * len(rows),
        }
    )


def _stats_frame(rows: list[tuple[str, str, int, int, float]]) -> pd.DataFrame:
    """option_daily_stats_sse shape: (code, name, call_vol, put_vol, pcr) — comma strings."""
    return pd.DataFrame(
        {
            "合约标的代码": [r[0] for r in rows],
            "合约标的名称": [r[1] for r in rows],
            "合约数量": [len(rows)] * len(rows),
            "总成交额": ["5,000,000"] * len(rows),
            "总成交量": [f"{r[2] + r[3]:,}" for r in rows],
            "认购成交量": [f"{r[2]:,}" for r in rows],
            "认沽成交量": [f"{r[3]:,}" for r in rows],
            "认沽/认购": [f"{r[4]:.2f}" for r in rows],
            "未平仓合约总数": ["1,000"] * len(rows),
            "未平仓认购合约数": ["600"] * len(rows),
            "未平仓认沽合约数": ["400"] * len(rows),
            "交易日": ["2026-09-29"] * len(rows),
        }
    )


def _install_fake_akshare(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[tuple[str, ...]],
    *,
    risk_by_date: dict[str, pd.DataFrame] | Exception | None = None,
    directory: pd.DataFrame | Exception | None = None,
    stats_by_date: dict[str, pd.DataFrame] | Exception | None = None,
    qvix: pd.DataFrame | Exception | None = None,
) -> None:
    """Fake akshare module injection — no network, exact endpoint surface."""

    def _serve(mapping: Any, key: str | None, name: str) -> pd.DataFrame:
        calls.append((name, key) if key else (name,))
        if isinstance(mapping, Exception):
            raise mapping
        if mapping is None:
            return pd.DataFrame()
        return mapping.get(key, pd.DataFrame()) if key is not None else pd.DataFrame()

    fake = types.ModuleType("akshare")

    def option_risk_indicator_sse(date: str = "20240626") -> pd.DataFrame:  # noqa: A002
        return _serve(risk_by_date, date, "risk")

    def option_current_day_sse() -> pd.DataFrame:
        calls.append(("directory",))
        if isinstance(directory, Exception):
            raise directory
        return directory if directory is not None else pd.DataFrame()

    def option_daily_stats_sse(date: str = "20240626") -> pd.DataFrame:  # noqa: A002
        return _serve(stats_by_date, date, "stats")

    def index_option_50etf_qvix() -> pd.DataFrame:
        calls.append(("qvix",))
        if isinstance(qvix, Exception):
            raise qvix
        return qvix if qvix is not None else pd.DataFrame()

    fake.option_risk_indicator_sse = option_risk_indicator_sse  # type: ignore[attr-defined]
    fake.option_current_day_sse = option_current_day_sse  # type: ignore[attr-defined]
    fake.option_daily_stats_sse = option_daily_stats_sse  # type: ignore[attr-defined]
    fake.index_option_50etf_qvix = index_option_50etf_qvix  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "akshare", fake)


def _qvix_frame(n: int, closes: list[float] | None = None) -> pd.DataFrame:
    start = date(2025, 1, 1)
    values = closes if closes is not None else [10.0 + i for i in range(n)]
    return pd.DataFrame(
        {
            "date": [(start + timedelta(days=i)).isoformat() for i in range(n)],
            "open": values,
            "high": [v + 0.5 for v in values],
            "low": [v - 0.5 for v in values],
            "close": values,
        }
    )


# ---------------------------------------------------------------------------
# Layer 2 — compute_iv_metrics
# ---------------------------------------------------------------------------


class TestComputeIvMetrics:
    def test_hand_calculated_surface_values(self) -> None:
        metrics = compute_iv_metrics(_two_expiry_contracts())

        assert metrics is not None
        assert metrics["status"] == "ok"
        assert metrics["atm_iv_near"] == pytest.approx(0.185)
        assert metrics["near_expiry"] == NEAR
        assert metrics["atm_iv_next"] == pytest.approx(0.210)
        assert metrics["next_expiry"] == NEXT
        # 0.185 - 0.210: negative = near-term elevated (inversion/fear)
        assert metrics["term_structure"] == pytest.approx(-0.025)
        # mean(0.175, 0.210) - mean(0.160, 0.150) = 0.1925 - 0.155
        assert metrics["skew_25d"] == pytest.approx(0.0375)
        assert metrics["n_contracts"] == 15
        assert metrics["n_filtered"] == 15

    def test_deep_itm_zero_iv_rows_are_filtered(self) -> None:
        contracts = _two_expiry_contracts() + [
            _contract(2.00, 1.00, 0.0),
            _contract(4.00, -1.00, 0.0, cp="P"),
        ]

        metrics = compute_iv_metrics(contracts)

        assert metrics is not None
        assert metrics["n_contracts"] == 17
        assert metrics["n_filtered"] == 15
        assert metrics["atm_iv_near"] == pytest.approx(0.185)  # ATM unaffected

    def test_high_abs_delta_rows_are_filtered(self) -> None:
        contracts = _two_expiry_contracts() + [_contract(2.00, 0.99, 0.30)]

        metrics = compute_iv_metrics(contracts)

        assert metrics is not None
        assert metrics["n_filtered"] == 15

    def test_single_expiry_has_no_term_structure(self) -> None:
        metrics = compute_iv_metrics(
            [c for c in _two_expiry_contracts() if c["expire_date"] == NEAR]
        )

        assert metrics is not None
        assert metrics["atm_iv_near"] == pytest.approx(0.185)
        assert metrics["atm_iv_next"] is None
        assert metrics["next_expiry"] is None
        assert metrics["term_structure"] is None

    def test_missing_delta_band_gives_no_skew(self) -> None:
        contracts = [c for c in _two_expiry_contracts() if c["expire_date"] == NEAR]
        # strip every put inside the -0.35..-0.15 band
        contracts = [c for c in contracts if not (c["cp"] == "P" and -0.35 <= c["delta"] <= -0.15)]
        contracts += [c for c in _two_expiry_contracts() if c["expire_date"] == NEXT]

        metrics = compute_iv_metrics(contracts)

        assert metrics is not None
        assert metrics["skew_25d"] is None
        assert metrics["term_structure"] == pytest.approx(-0.025)  # skew-independent

    def test_fewer_than_ten_usable_rows_returns_none(self) -> None:
        contracts = [c for c in _two_expiry_contracts() if c["expire_date"] == NEAR][:9]

        assert compute_iv_metrics(contracts) is None

    def test_atm_tie_prefers_lower_strike(self) -> None:
        rows = (
            [
                _contract(2.95, 0.48, 0.100),
                _contract(3.05, 0.52, 0.300),
            ]
            + [_contract(3.20 + i * 0.10, 0.12 + 0.01 * i, 0.150 + 0.001 * i) for i in range(4)]
            + [
                _contract(2.70 - i * 0.10, -0.12 - 0.01 * i, 0.160 + 0.001 * i, cp="P")
                for i in range(4)
            ]
        )

        metrics = compute_iv_metrics(rows)

        assert metrics is not None
        assert metrics["atm_iv_near"] == pytest.approx(0.100)

    def test_puts_only_expiry_takes_closest_put_as_atm(self) -> None:
        rows = [_contract(3.00, -0.50, 0.190, cp="P")] + [
            _contract(3.00 - 0.10 * i, -0.10 - 0.04 * i, 0.150, cp="P") for i in range(1, 10)
        ]

        metrics = compute_iv_metrics(rows)

        assert metrics is not None
        assert metrics["atm_iv_near"] == pytest.approx(0.190)

    def test_none_and_empty_inputs_return_none(self) -> None:
        assert compute_iv_metrics(None) is None
        assert compute_iv_metrics([]) is None


# ---------------------------------------------------------------------------
# Layer 3 — compute_pcr
# ---------------------------------------------------------------------------


class TestComputePcr:
    def test_market_pcr_is_volume_weighted_aggregate(self) -> None:
        pcr_by_underlying = {
            "510050": {
                "name": "上证50ETF",
                "pcr_volume": 0.8,
                "call_volume": 1000.0,
                "put_volume": 800.0,
                "trade_date": "2026-09-29",
            },
            "510300": {
                "name": "沪深300ETF",
                "pcr_volume": 1.2,
                "call_volume": 500.0,
                "put_volume": 600.0,
                "trade_date": "2026-09-29",
            },
        }

        result = compute_pcr(pcr_by_underlying)

        assert result is not None
        # (800 + 600) / (1000 + 500)
        assert result["market_pcr"] == pytest.approx(1400.0 / 1500.0)
        assert result["by_underlying"]["510050"]["name"] == "上证50ETF"
        assert result["by_underlying"]["510300"]["pcr_volume"] == 1.2

    def test_volumes_missing_gives_none_market_pcr(self) -> None:
        result = compute_pcr(
            {"510050": {"name": "50ETF", "pcr_volume": 0.9, "call_volume": 0, "put_volume": 0}}
        )

        assert result is not None
        assert result["market_pcr"] is None

    def test_none_input_returns_none(self) -> None:
        assert compute_pcr(None) is None
        assert compute_pcr({}) is None


# ---------------------------------------------------------------------------
# Layer 4 — build_option_implied
# ---------------------------------------------------------------------------


class TestBuildOptionImplied:
    @pytest.mark.parametrize(
        ("percentile", "expected_regime"),
        [(0.80, "恐慌"), (0.95, "恐慌"), (0.20, "自满"), (0.05, "自满"), (0.45, "中性")],
    )
    def test_regime_labels_from_qvix_percentile(
        self, percentile: float, expected_regime: str
    ) -> None:
        qvix = {"current": 25.0, "as_of": "2026-09-29", "percentile_1y": percentile}

        block = build_option_implied(None, None, qvix)

        assert block["status"] == "ok"
        assert block["regime"] == expected_regime
        assert block["qvix"] == qvix
        assert block["iv"] is None
        assert block["pcr"] is None
        assert block["generated_at"]

    def test_qvix_absent_gives_no_regime(self) -> None:
        block = build_option_implied({"atm_iv_near": 0.185}, {"market_pcr": 0.9}, None)

        assert block["status"] == "insufficient_data"
        assert block["regime"] is None
        assert block["iv"] == {"atm_iv_near": 0.185}
        assert block["pcr"] == {"market_pcr": 0.9}

    def test_qvix_percentile_none_gives_no_regime(self) -> None:
        block = build_option_implied(None, None, {"current": 20.0, "percentile_1y": None})

        assert block["status"] == "insufficient_data"
        assert block["regime"] is None


# ---------------------------------------------------------------------------
# Layer 1 — fetch_sse_option_snapshot
# ---------------------------------------------------------------------------


def _full_trio_frames() -> dict[str, Any]:
    risk = _risk_frame(
        "2026-09-29",
        [
            ("10005001", "50ETF购9月2900", 0.50, 0.185),
            ("10005002", "50ETF沽9月2900", -0.50, 0.210),
            ("10005003", "50ETF购9月2800", 0.80, 0.220),
        ],
    )
    directory = _dir_frame(
        [
            ("880001", "10005001", "50ETF购9月2900", "50ETF(510050)", "认购", 2.90, "2026-09-24"),
            ("880002", "10005002", "50ETF沽9月2900", "50ETF(510050)", "认沽", 2.90, "2026-09-24"),
            ("880004", "10005009", "50ETF购9月3000", "50ETF(510050)", "认购", 3.00, "2026-09-24"),
        ]
    )
    stats = _stats_frame([("510050", "上证50ETF", 1000, 900, 0.90)])
    return {"risk": risk, "directory": directory, "stats": stats}


class TestFetchSseOptionSnapshot:
    def test_join_directory_and_pcr(self, monkeypatch) -> None:
        frames = _full_trio_frames()
        today = date.today().strftime("%Y%m%d")
        calls: list[tuple[str, ...]] = []
        _install_fake_akshare(
            monkeypatch,
            calls,
            risk_by_date={today: frames["risk"]},
            directory=frames["directory"],
            stats_by_date={today: frames["stats"]},
        )

        snapshot = fetch_sse_option_snapshot()

        assert snapshot is not None
        assert snapshot["status"] == "ok"
        assert snapshot["as_of"] == "2026-09-29"
        contracts = snapshot["contracts"]
        assert contracts is not None
        assert contracts[0] == {
            "contract_id": "10005001",
            "symbol": "510050",
            "cp": "C",
            "strike": 2.90,
            "expire_date": "2026-09-24",
            "delta": 0.50,
            "iv": 0.185,
        }
        assert contracts[1]["cp"] == "P"
        assert contracts[1]["iv"] == pytest.approx(0.210)
        assert snapshot["n_unmatched"] == 1  # 10005009 has no risk-table row
        pcr = snapshot["pcr_by_underlying"]
        assert pcr is not None
        assert pcr["510050"]["name"] == "上证50ETF"
        assert pcr["510050"]["pcr_volume"] == pytest.approx(0.90)
        assert pcr["510050"]["call_volume"] == 1000.0  # comma strings parsed
        assert pcr["510050"]["put_volume"] == 900.0
        assert provider_health_snapshot()["providers"]["sse-options"]["ok"] == 1

    def test_walkback_to_previous_day_when_today_empty(self, monkeypatch) -> None:
        frames = _full_trio_frames()
        today = date.today()
        calls: list[tuple[str, ...]] = []
        _install_fake_akshare(
            monkeypatch,
            calls,
            risk_by_date={(today - timedelta(days=1)).strftime("%Y%m%d"): frames["risk"]},
            directory=frames["directory"],
            stats_by_date={(today - timedelta(days=1)).strftime("%Y%m%d"): frames["stats"]},
        )

        snapshot = fetch_sse_option_snapshot()

        assert snapshot is not None
        assert snapshot["contracts"] is not None
        assert snapshot["as_of"] == "2026-09-29"
        risk_calls = [c for c in calls if c[0] == "risk"]
        assert risk_calls == [
            ("risk", today.strftime("%Y%m%d")),
            ("risk", (today - timedelta(days=1)).strftime("%Y%m%d")),
        ]

    def test_directory_failure_degrades_with_pcr_intact(self, monkeypatch) -> None:
        frames = _full_trio_frames()
        today = date.today().strftime("%Y%m%d")
        calls: list[tuple[str, ...]] = []
        _install_fake_akshare(
            monkeypatch,
            calls,
            risk_by_date={today: frames["risk"]},
            directory=RuntimeError("directory endpoint down"),
            stats_by_date={today: frames["stats"]},
        )

        snapshot = fetch_sse_option_snapshot()

        assert snapshot is not None
        assert snapshot["status"] == "degraded"
        assert snapshot["contracts"] is None
        assert snapshot["n_unmatched"] is None
        assert snapshot["pcr_by_underlying"] is not None
        assert snapshot["as_of"] == "2026-09-29"

    def test_daily_stats_failure_keeps_contracts(self, monkeypatch) -> None:
        frames = _full_trio_frames()
        today = date.today().strftime("%Y%m%d")
        _install_fake_akshare(
            monkeypatch,
            [],
            risk_by_date={today: frames["risk"]},
            directory=frames["directory"],
            stats_by_date=RuntimeError("stats endpoint down"),
        )

        snapshot = fetch_sse_option_snapshot()

        assert snapshot is not None
        assert snapshot["status"] == "ok"
        assert snapshot["contracts"] is not None
        assert snapshot["pcr_by_underlying"] is None

    def test_total_failure_returns_none_and_records_fail(self, monkeypatch) -> None:
        calls: list[tuple[str, ...]] = []
        _install_fake_akshare(
            monkeypatch,
            calls,
            risk_by_date=ConnectionError("SSE unreachable"),
        )

        assert fetch_sse_option_snapshot() is None
        providers = provider_health_snapshot()["providers"]
        assert providers["sse-options"]["fail"] == 1
        assert len([c for c in calls if c[0] == "risk"]) == 6  # walkback budget

    def test_success_is_cached_second_call_hits_no_network(self, monkeypatch) -> None:
        frames = _full_trio_frames()
        today = date.today().strftime("%Y%m%d")
        calls: list[tuple[str, ...]] = []
        _install_fake_akshare(
            monkeypatch,
            calls,
            risk_by_date={today: frames["risk"]},
            directory=frames["directory"],
            stats_by_date={today: frames["stats"]},
        )

        first = fetch_sse_option_snapshot()
        second = fetch_sse_option_snapshot()

        assert second == first
        assert len(calls) == 3  # risk + directory + stats, once only

    def test_missing_akshare_returns_none(self, monkeypatch) -> None:
        monkeypatch.setitem(sys.modules, "akshare", None)

        assert fetch_sse_option_snapshot() is None


# ---------------------------------------------------------------------------
# Layer 1 — fetch_qvix_context
# ---------------------------------------------------------------------------


class TestFetchQvixContext:
    def test_fetch_ok_upserts_store_and_computes_percentile(self, monkeypatch, store) -> None:
        calls: list[tuple[str, ...]] = []
        _install_fake_akshare(monkeypatch, calls, qvix=_qvix_frame(252))  # closes 10..261 ascending

        context = fetch_qvix_context(store)

        assert context is not None
        assert context["current"] == pytest.approx(261.0)
        assert context["as_of"] == (date(2025, 1, 1) + timedelta(days=251)).isoformat()
        assert context["percentile_1y"] == 1.0  # current is the max of the window
        assert context["history_days"] == 252
        assert store.row_count() == 252
        assert provider_health_snapshot()["providers"]["qvix"]["ok"] == 1

    def test_short_history_computes_percentile_when_at_least_30_rows(
        self, monkeypatch, store
    ) -> None:
        _install_fake_akshare(monkeypatch, [], qvix=_qvix_frame(40))

        context = fetch_qvix_context(store)

        assert context is not None
        assert context["percentile_1y"] == 1.0

    def test_too_short_history_gives_none_percentile(self, monkeypatch, store) -> None:
        _install_fake_akshare(monkeypatch, [], qvix=_qvix_frame(29))

        context = fetch_qvix_context(store)

        assert context is not None
        assert context["current"] == pytest.approx(38.0)
        assert context["percentile_1y"] is None

    def test_fetch_failure_serves_populated_store_as_fallback(self, monkeypatch, store) -> None:
        start = date(2025, 1, 1)
        store.upsert_many([((start + timedelta(days=i)).isoformat(), 20.0) for i in range(300)])
        _install_fake_akshare(monkeypatch, [], qvix=ConnectionError("optbbs down"))

        context = fetch_qvix_context(store)

        assert context is not None
        assert context["current"] == pytest.approx(20.0)
        assert context["as_of"] == (start + timedelta(days=299)).isoformat()
        assert context["percentile_1y"] == 1.0
        assert context["history_days"] == 300
        providers = provider_health_snapshot()["providers"]
        assert providers["qvix"]["fallback"] == 1

    def test_fetch_failure_and_empty_store_returns_none(self, monkeypatch, store) -> None:
        _install_fake_akshare(monkeypatch, [], qvix=ConnectionError("optbbs down"))

        assert fetch_qvix_context(store) is None
        assert provider_health_snapshot()["providers"]["qvix"]["fail"] == 1


# ---------------------------------------------------------------------------
# qvix_store
# ---------------------------------------------------------------------------


class TestQvixStore:
    def test_upsert_is_idempotent_last_write_wins(self, tmp_path) -> None:
        store = QvixStore(db_path=tmp_path / "qvix.db")

        store.upsert_many([("2026-09-29", 15.0)])
        store.upsert_many([("2026-09-29", 15.5)])

        assert store.row_count() == 1
        assert store.last_row() == ("2026-09-29", 15.5)

    def test_trailing_closes_descending_with_limit(self, tmp_path) -> None:
        store = QvixStore(db_path=tmp_path / "qvix.db")
        start = date(2026, 1, 1)
        store.upsert_many(
            [((start + timedelta(days=i)).isoformat(), float(i + 1)) for i in range(10)]
        )

        assert store.trailing_closes(3) == [10.0, 9.0, 8.0]
        assert store.trailing_closes(100) == [float(10 - i) for i in range(10)]

    def test_broken_db_file_never_raises(self, tmp_path) -> None:
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory")  # parent path is a file → connect fails
        store = QvixStore(db_path=blocker / "sub" / "qvix.db")

        store.upsert_many([("2026-09-29", 15.0)])
        assert store.trailing_closes(10) == []
        assert store.last_row() is None
        assert store.row_count() == 0
