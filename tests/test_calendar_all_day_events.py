"""tests/test_calendar_all_day_events.py — all-day events.

Confirmed live: "Put on my calendar September 1st Highschool Starts" came
back "Wasn't sure what to schedule there, boss -- try again with a time?"
That's a date with no clock time -- an ordinary all-day event -- but
create_event() only ever sent Google's timed-event fields, and the
extraction prompt told the model to give up unless a *time* was present.
The boss was being pushed to invent a time for something that has none.

Google's model: {"date": ...} for all-day, {"dateTime": ...} for timed,
and all-day end.date is EXCLUSIVE -- the subtlety that makes a
single-day event land zero-length if passed through naively.
"""
from unittest import mock

import pytest

import services.friday_calendar as cal_mod
from services.friday_calendar import FridayCalendar


class _Resp:
    status_code = 200

    @staticmethod
    def json():
        return {"htmlLink": "https://calendar.google.com/event?eid=abc"}


@pytest.fixture
def connected(monkeypatch):
    cal = FridayCalendar()
    monkeypatch.setattr(cal, "_get_access_token", lambda: "token-123")
    return cal


def _sent_body(fake_post):
    return fake_post.call_args.kwargs["json"]


class TestAllDayEvents:

    def test_a_single_day_event_uses_date_fields_not_datetime(self, connected):
        fake_post = mock.Mock(return_value=_Resp())
        with mock.patch("httpx.post", fake_post):
            result = connected.create_event("Highschool Starts", "2026-09-01", "2026-09-01")

        assert result["ok"] is True
        body = _sent_body(fake_post)
        assert "date" in body["start"] and "dateTime" not in body["start"]
        assert body["start"]["date"] == "2026-09-01"

    def test_a_single_day_events_end_is_the_next_day(self, connected):
        """Google treats all-day end.date as exclusive. Sending the same
        date for start and end produces a zero-length event that renders
        wrong -- this is the bug that would survive a naive fix."""
        fake_post = mock.Mock(return_value=_Resp())
        with mock.patch("httpx.post", fake_post):
            connected.create_event("Highschool Starts", "2026-09-01", "2026-09-01")

        body = _sent_body(fake_post)
        assert body["end"]["date"] == "2026-09-02"

    def test_a_multi_day_range_keeps_its_span(self, connected):
        """"the 1st to the 3rd" is three days: 09-01 through 09-03
        inclusive, sent as an exclusive end of 09-04."""
        fake_post = mock.Mock(return_value=_Resp())
        with mock.patch("httpx.post", fake_post):
            connected.create_event("Conference", "2026-09-01", "2026-09-03")

        body = _sent_body(fake_post)
        assert body["start"]["date"] == "2026-09-01"
        assert body["end"]["date"] == "2026-09-04"

    def test_month_and_year_rollover_is_handled(self, connected):
        """Naive string/day arithmetic breaks here; real date math
        doesn't."""
        fake_post = mock.Mock(return_value=_Resp())
        with mock.patch("httpx.post", fake_post):
            connected.create_event("New Year's Eve", "2026-12-31", "2026-12-31")

        assert _sent_body(fake_post)["end"]["date"] == "2027-01-01"

    def test_leap_day_rollover_is_handled(self, connected):
        fake_post = mock.Mock(return_value=_Resp())
        with mock.patch("httpx.post", fake_post):
            connected.create_event("Leap Day", "2028-02-29", "2028-02-29")

        assert _sent_body(fake_post)["end"]["date"] == "2028-03-01"


class TestTimedEventsAreUnaffected:
    """The all-day path must not cost the existing timed-event
    behavior."""

    def test_a_timed_event_still_uses_datetime_fields(self, connected):
        fake_post = mock.Mock(return_value=_Resp())
        with mock.patch("httpx.post", fake_post):
            connected.create_event(
                "Standup", "2026-09-01T15:00:00", "2026-09-01T15:30:00"
            )

        body = _sent_body(fake_post)
        assert body["start"]["dateTime"] == "2026-09-01T15:00:00"
        # Timed ends are exact, never shifted a day.
        assert body["end"]["dateTime"] == "2026-09-01T15:30:00"

    def test_a_mixed_pair_is_treated_as_timed_not_all_day(self, connected):
        """Only a date-only pair means all-day; a half-specified pair
        must not silently become one and lose its time."""
        fake_post = mock.Mock(return_value=_Resp())
        with mock.patch("httpx.post", fake_post):
            connected.create_event("Odd one", "2026-09-01", "2026-09-01T15:30:00")

        body = _sent_body(fake_post)
        assert "dateTime" in body["start"] and "dateTime" in body["end"]


class TestDateOnlyDetection:

    @pytest.mark.parametrize("value", ["2026-09-01", " 2026-09-01 "])
    def test_date_only_values_are_recognized(self, value):
        assert cal_mod.FridayCalendar._is_date_only(value) is True

    @pytest.mark.parametrize(
        "value",
        ["2026-09-01T15:00:00", "", "not-a-date", "2026-9-1", "2026-09-01T00:00:00Z"],
    )
    def test_non_date_only_values_are_rejected(self, value):
        assert cal_mod.FridayCalendar._is_date_only(value) is False
