"""tests/test_calendar_connectivity_question.py —
core.friday_brain._instant_response()'s calendar guard.

Flagged as a known follow-up in PR #49: "is my calendar even connected"
matches the guard's "my calendar" substring check and used to fall
straight into the today's-events branch, answering with a guess at
what's on the calendar instead of the yes/no connectivity question
actually asked. That only implies "yes, connected" when there happen to
be events, and gives no distinguishable answer at all when the calendar
is connected but simply empty for the day.
"""
from unittest import mock

import core.friday_brain as brain_mod
from core.friday_brain import friday_brain


class TestConnectivityQuestionGetsADirectAnswer:

    def test_the_exact_reported_phrase_gets_a_yes_not_todays_events(self):
        fake_cal = mock.Mock()
        fake_cal.is_connected.return_value = True
        fake_cal.get_today.return_value = [{"title": "Dentist"}]

        with mock.patch("services.friday_calendar.friday_calendar", fake_cal):
            answer = friday_brain._instant_response("is my calendar even connected")

        assert answer == "Yes, boss — your calendar's connected."
        # Must answer directly from is_connected(), not by inferring
        # "connected" from there being events today.
        fake_cal.get_today.assert_not_called()

    def test_a_disconnected_calendar_still_says_so_plainly(self):
        fake_cal = mock.Mock()
        fake_cal.is_connected.return_value = False

        with mock.patch("services.friday_calendar.friday_calendar", fake_cal):
            answer = friday_brain._instant_response("is my calendar connected")

        assert answer == "Your calendar isn't connected yet, boss."

    def test_hooked_up_phrasing_is_also_recognised(self):
        fake_cal = mock.Mock()
        fake_cal.is_connected.return_value = True

        with mock.patch("services.friday_calendar.friday_calendar", fake_cal):
            answer = friday_brain._instant_response("is my calendar hooked up yet")

        assert answer == "Yes, boss — your calendar's connected."


class TestActualScheduleQuestionsStillShowEvents:
    """The guard must not cost the guard its original job -- a genuine
    "what's on my calendar" still needs to answer with events, not get
    misread as a connectivity check."""

    def test_whats_on_my_calendar_still_lists_events(self):
        fake_cal = mock.Mock()
        fake_cal.is_connected.return_value = True
        fake_cal.get_today.return_value = [{"title": "Lunch with Jane"}]

        with mock.patch("services.friday_calendar.friday_calendar", fake_cal):
            answer = friday_brain._instant_response("what's on my calendar today")

        assert "Lunch with Jane" in answer

    def test_an_empty_but_connected_calendar_says_nothing_today(self):
        fake_cal = mock.Mock()
        fake_cal.is_connected.return_value = True
        fake_cal.get_today.return_value = []

        with mock.patch("services.friday_calendar.friday_calendar", fake_cal):
            answer = friday_brain._instant_response("any meetings today")

        assert answer == "Nothing on your calendar today, boss."

    def test_a_genuine_calendar_add_request_is_not_swallowed_by_the_connect_check(self):
        """"set up a meeting on my calendar" carries "my calendar" (the
        outer guard) but must not also match the connectivity check just
        because it happens to contain calendar language -- it's not
        asking about connectivity at all. (This phrasing doesn't match
        any of CALENDAR_ADD_TRIGGERS in server.py either, so it's exactly
        the kind of request that reaches this fallback for real.)"""
        fake_cal = mock.Mock()
        fake_cal.is_connected.return_value = True
        fake_cal.get_today.return_value = []

        with mock.patch("services.friday_calendar.friday_calendar", fake_cal):
            answer = friday_brain._instant_response("set up a meeting on my calendar")

        assert answer == "Nothing on your calendar today, boss."
