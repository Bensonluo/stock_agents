"""Technical-section sparkline series.

The technical card renders a price sparkline per symbol, but the report
only carried verdicts — never a price series. These tests pin the wire:
``_technical`` attaches the last ~90 rounded closes when history exists
and leaves the key absent otherwise (degraded convention).
"""

from __future__ import annotations

import math

from app.services.report_service import SPARK_BARS, ReportService


def _data(closes: list | None) -> dict:
    market: dict = {"symbol": "TEST", "current_price": 10.0}
    if closes is not None:
        market["historical_data"] = {
            "dates": [f"2026-01-{i % 28 + 1:02d}" for i in range(len(closes))],
            "close": closes,
        }
    return {
        "symbols": ["TEST"],
        "query": "TEST spark",
        "market_data": {"TEST": market},
        "technical_analysis": {"TEST": {"signals": {"trend": "neutral"}, "sentiment": {}}},
    }


def _spark(data: dict) -> list | None:
    return ReportService.build_sections(data)["technical_analysis"]["by_symbol"]["TEST"].get(
        "price_spark"
    )


class TestPriceSpark:
    def test_long_history_is_capped_to_the_recent_tail(self) -> None:
        closes = [10.0 + i * 0.5 for i in range(SPARK_BARS + 30)]

        spark = _spark(_data(closes))

        assert len(spark) == SPARK_BARS
        # Tail, not head: first spark bar is the (len - SPARK_BARS)-th close.
        assert spark[0] == round(closes[-SPARK_BARS], 2)
        assert spark[-1] == round(closes[-1], 2)

    def test_short_history_passes_every_bar_rounded(self) -> None:
        spark = _spark(_data([10.0, 10.125, 10.333333]))

        # 10.125 is 10.12499… in binary; round-half-even lands on 10.12.
        assert spark == [10.0, 10.12, 10.33]

    def test_missing_history_leaves_the_key_absent(self) -> None:
        assert _spark(_data(None)) is None

        no_close = _data([1.0])
        no_close["market_data"]["TEST"]["historical_data"] = {"dates": ["2026-01-01"]}
        assert _spark(no_close) is None

    def test_non_finite_values_are_dropped_not_serialized(self) -> None:
        spark = _spark(_data([10.0, float("nan"), math.inf, 11.0]))

        assert spark == [10.0, 11.0]
