"""Contract pins for date validation across the backtest-family request models.

V1 BacktestRequest enforces calendar-realness plus end > start (its
parametrized pins live in test_backtest.py); V2BacktestRequest — and
WalkForwardRequest through inheritance — enforces both via the ordering
validator's strptime. CalibrateRequest enforced neither: a
calendar-impossible "2023-02-30" or a reversed range cleared the regex
pattern and flowed into the service layer as-is. These pins hold the whole
family to the same contract.
"""

import pytest
from pydantic import ValidationError

from app.api.routes.backtest import CalibrateRequest, V2BacktestRequest

CALIBRATE_BASE = {
    "symbol": "AAPL",
    "strategy": "sma_crossover",
    "start_date": "2023-01-01",
    "end_date": "2024-01-01",
}

V2_BASE = {
    "symbol": "AAPL",
    "strategy": "sma_crossover",
    "start_date": "2023-01-01",
    "end_date": "2024-01-01",
}


class TestCalibrateRequestDateValidation:
    @pytest.mark.parametrize(
        "updates",
        [
            {"start_date": "2023-02-30"},  # matches the pattern, rolls to March
            {"end_date": "2023-02-29"},  # 2023 is not a leap year
        ],
    )
    def test_calendar_impossible_dates_rejected(self, updates: dict[str, str]) -> None:
        with pytest.raises(ValidationError):
            CalibrateRequest.model_validate({**CALIBRATE_BASE, **updates})

    @pytest.mark.parametrize(
        "updates",
        [
            {"end_date": "2023-01-01"},  # same day: end <= start
            {"end_date": "2022-01-01"},  # reversed range
        ],
    )
    def test_non_increasing_range_rejected(self, updates: dict[str, str]) -> None:
        with pytest.raises(ValidationError):
            CalibrateRequest.model_validate({**CALIBRATE_BASE, **updates})

    def test_well_formed_range_accepted(self) -> None:
        request = CalibrateRequest.model_validate(CALIBRATE_BASE)
        assert request.start_date == "2023-01-01"
        assert request.end_date == "2024-01-01"


class TestV2DateValidation:
    """V2 enforces the same contract through _dates_in_order's strptime —
    these pins lock the inherited contract (WalkForwardRequest included)
    against regressions."""

    def test_calendar_impossible_date_rejected(self) -> None:
        with pytest.raises(ValidationError):
            V2BacktestRequest.model_validate({**V2_BASE, "start_date": "2023-02-30"})

    def test_non_increasing_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            V2BacktestRequest.model_validate({**V2_BASE, "end_date": "2023-01-01"})

    def test_well_formed_range_accepted(self) -> None:
        request = V2BacktestRequest.model_validate(V2_BASE)
        assert request.end_date == "2024-01-01"
