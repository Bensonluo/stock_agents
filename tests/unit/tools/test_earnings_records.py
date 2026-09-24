"""earnings_records — the date-surviving conversion for yfinance frames.

``to_dict("records")`` drops the DatetimeIndex entirely: the stored
earnings_dates payload had EPS estimates attached to nothing. These tests
pin the fix — the date reaches the records — plus NaN hygiene (NaN is not
valid strict JSON) and column tolerance across yfinance's spellings.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from app.tools.data.fetcher import earnings_records


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "EPS Estimate": [1.20, 1.35],
            "Reported EPS": [1.25, np.nan],
            "Surprise(%)": [4.1, -2.0],
        },
        index=pd.DatetimeIndex(["2026-06-30", "2026-09-30"], name="Earnings Date"),
    )


class TestEarningsRecords:
    def test_dates_survive_the_conversion(self) -> None:
        records = earnings_records(_frame())

        assert [record["date"] for record in records] == ["2026-06-30", "2026-09-30"]

    def test_value_columns_map_through_aliases(self) -> None:
        records = earnings_records(_frame())

        assert records[0]["eps_estimate"] == 1.2
        assert records[0]["eps_actual"] == 1.25
        assert records[0]["surprise_pct"] == 4.1

    def test_nan_becomes_none_not_json_poison(self) -> None:
        records = earnings_records(_frame())

        assert records[1]["eps_actual"] is None

    def test_missing_columns_omit_their_keys(self) -> None:
        frame = pd.DataFrame(
            {"EPS Estimate": [1.0]},
            index=pd.DatetimeIndex(["2026-12-31"]),
        )

        records = earnings_records(frame)

        assert records == [{"date": "2026-12-31", "eps_estimate": 1.0}]

    def test_alternate_surprise_spelling_maps_too(self) -> None:
        frame = pd.DataFrame(
            {"EPS Estimate": [1.0], "Surprise Pct": [3.3]},
            index=pd.DatetimeIndex(["2026-12-31"]),
        )

        records = earnings_records(frame)

        assert records[0]["surprise_pct"] == 3.3

    def test_none_and_empty_frames_give_empty_list(self) -> None:
        assert earnings_records(None) == []
        assert earnings_records(pd.DataFrame()) == []

    def test_non_finite_values_never_reach_the_records(self) -> None:
        frame = pd.DataFrame(
            {"EPS Estimate": [math.inf, 1.0]},
            index=pd.DatetimeIndex(["2026-06-30", "2026-09-30"]),
        )

        records = earnings_records(frame)

        assert records[0]["eps_estimate"] is None
        assert records[1]["eps_estimate"] == 1.0


class TestYfinanceProviderWiring:
    def test_provider_payload_carries_the_earnings_calendar(self, monkeypatch):
        """ReAct path parity: the yfinance provider snapshot must include
        earnings_dates — the report's event window depends on it."""
        import asyncio
        import sys
        from types import ModuleType

        from app.tools.data import fetcher

        class _Ticker:
            info = {
                "currentPrice": 101.0,
                "previousClose": 100.0,
                "trailingPE": 10.0,
            }
            earnings_dates = _frame()
            news = []

            def history(self, **kwargs):
                return pd.DataFrame(
                    {
                        "Open": [99.0, 100.0],
                        "High": [101.0, 102.0],
                        "Low": [98.0, 99.0],
                        "Close": [100.0, 101.0],
                        "Volume": [1_000, 1_100],
                    },
                    index=pd.to_datetime(["2026-01-02", "2026-01-03"]),
                )

        fake_yf = ModuleType("yfinance")
        fake_yf.Ticker = lambda _symbol: _Ticker()
        monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

        result = asyncio.run(fetcher._yfinance_fetch("AAPL"))

        dates = [record["date"] for record in result["financial_data"]["earnings_dates"]]
        assert dates == ["2026-06-30", "2026-09-30"]
