"""Next-earnings window — pure calendar math over record lists.

The window must be honest about absence: an empty feed, a calendar of
already-reported quarters, or garbage dates yield None, never a defaulted
"today". Dates are anchored dynamically to ``date.today()`` so the default
``as_of`` tests never rot.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.analysis.events import next_earnings_window

TODAY = date.today()


def _records(*days_from_today: int) -> list[dict]:
    return [
        {"date": (TODAY + timedelta(days=offset)).isoformat(), "eps_estimate": 1.0}
        for offset in days_from_today
    ]


class TestNextEarningsWindow:
    def test_picks_earliest_future_date_from_unsorted_records(self) -> None:
        window = next_earnings_window(_records(45, 10, 90), as_of=TODAY)

        assert window == {
            "next_earnings_date": (TODAY + timedelta(days=10)).isoformat(),
            "days_until": 10,
        }

    def test_same_day_earnings_is_zero_days_out(self) -> None:
        window = next_earnings_window(_records(0), as_of=TODAY)

        assert window == {"next_earnings_date": TODAY.isoformat(), "days_until": 0}

    def test_past_quarters_are_ignored(self) -> None:
        window = next_earnings_window(_records(-30, -60, 14), as_of=TODAY)

        assert window is not None
        assert window["days_until"] == 14

    def test_all_past_or_empty_returns_none(self) -> None:
        assert next_earnings_window(_records(-30), as_of=TODAY) is None
        assert next_earnings_window([], as_of=TODAY) is None
        assert next_earnings_window(None, as_of=TODAY) is None

    def test_garbage_records_do_not_crash_and_do_not_count(self) -> None:
        records = [
            {"date": "not-a-date"},
            {"eps_estimate": 1.0},  # no date key
            "junk",
            {"date": (TODAY + timedelta(days=3)).isoformat()},
        ]

        window = next_earnings_window(records, as_of=TODAY)  # type: ignore[arg-type]

        assert window is not None
        assert window["days_until"] == 3

    def test_string_as_of_is_accepted(self) -> None:
        window = next_earnings_window([{"date": "2030-06-15"}], as_of="2030-06-01")

        assert window == {"next_earnings_date": "2030-06-15", "days_until": 14}

    def test_default_as_of_is_today(self) -> None:
        window = next_earnings_window(_records(7))

        assert window is not None
        assert window["next_earnings_date"] == (TODAY + timedelta(days=7)).isoformat()
