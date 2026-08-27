"""tests/test_calendar_add.py — _cmd_calendar_add's pending-reply state,
the same fix applied to the same underlying gap as
_cmd_email_compose_send: "wasn't sure what to schedule there -- try
again with a time?" invites a bare reply ("3pm tomorrow") that carries
none of CALENDAR_ADD_TRIGGERS' phrases. Without this, that reply falls
through to the plain conversational model, which can describe
"scheduling" the event in prose without ever calling create_event().
"""
import time as time_module
from unittest import mock

import server


def _think(payload):
    return {"response": payload, "model": "test", "ms": 1}


class TestNewRequest:
    def test_no_trigger_and_nothing_pending_returns_none(self, app):
        with app.test_request_context():
            result = server._cmd_calendar_add("what time is it", "what time is it")
        assert result is None

    def test_calendar_not_connected(self, app):
        with app.test_request_context(), \
             mock.patch("server.friday_brain", mock.Mock()), \
             mock.patch("server.friday_calendar", None):
            prompt = "add to my calendar lunch at noon"
            result = server._cmd_calendar_add(prompt, prompt.lower())

        assert result is not None
        assert "isn't connected" in result.get_json()["response"]

    def test_complete_extraction_creates_event(self, app):
        fake_brain = mock.Mock()
        fake_brain.think.return_value = _think(
            '{"title": "Lunch", "start": "2026-01-01T12:00:00", "end": "2026-01-01T12:30:00"}'
        )
        fake_cal = mock.Mock()
        fake_cal.is_connected.return_value = True
        fake_cal.create_event.return_value = {"ok": True}

        with app.test_request_context(), \
             mock.patch("server.friday_brain", fake_brain), \
             mock.patch("server.friday_calendar", fake_cal):
            prompt = "add to my calendar lunch at noon"
            result = server._cmd_calendar_add(prompt, prompt.lower())

        assert result is not None
        body = result.get_json()
        assert "Added" in body["response"]
        fake_cal.create_event.assert_called_once()
        assert server._pending_calendar_add == {}

    def test_incomplete_extraction_sets_pending_and_asks(self, app):
        fake_brain = mock.Mock()
        fake_brain.think.return_value = _think('{"title": "", "start": "", "end": ""}')
        fake_cal = mock.Mock()
        fake_cal.is_connected.return_value = True

        with app.test_request_context(), \
             mock.patch("server.friday_brain", fake_brain), \
             mock.patch("server.friday_calendar", fake_cal):
            prompt = "schedule a meeting with Jane"
            result = server._cmd_calendar_add(prompt, prompt.lower())

        assert result is not None
        body = result.get_json()
        # "with a time" was the old wording, and became actively
        # misleading once all-day events were supported -- a bare date is
        # enough now, so asking for a time sends the boss down a path
        # that isn't required. See tests/test_calendar_all_day_events.py.
        assert "try again with a date" in body["response"].lower()
        fake_cal.create_event.assert_not_called()
        assert server._pending_calendar_add != {}
        assert "context" in server._pending_calendar_add


class TestPendingReply:
    def test_trigger_less_reply_completes_and_actually_creates_the_event(self, app):
        """The exact bug: a bare time reply carrying none of
        CALENDAR_ADD_TRIGGERS' phrases must still reach create_event(),
        not fall through to a fabricated "got it, scheduled" chat reply."""
        server._pending_calendar_add = {
            "context": "schedule a meeting with Jane", "expires": time_module.time() + 300,
        }
        fake_brain = mock.Mock()
        fake_brain.think.return_value = _think(
            '{"title": "Meeting with Jane", "start": "2026-01-01T15:00:00", "end": "2026-01-01T15:30:00"}'
        )
        fake_cal = mock.Mock()
        fake_cal.is_connected.return_value = True
        fake_cal.create_event.return_value = {"ok": True}

        with app.test_request_context(), \
             mock.patch("server.friday_brain", fake_brain), \
             mock.patch("server.friday_calendar", fake_cal):
            prompt = "3pm tomorrow"
            result = server._cmd_calendar_add(prompt, prompt.lower())

        assert result is not None
        body = result.get_json()
        assert "Added" in body["response"]
        fake_cal.create_event.assert_called_once()
        sent_prompt = fake_brain.think.call_args[0][0]
        assert "schedule a meeting with Jane" in sent_prompt
        assert "3pm tomorrow" in sent_prompt

    def test_second_miss_gives_up_instead_of_looping(self, app):
        server._pending_calendar_add = {
            "context": "schedule a meeting", "expires": time_module.time() + 300,
        }
        fake_brain = mock.Mock()
        fake_brain.think.return_value = _think('{"title": "", "start": "", "end": ""}')
        fake_cal = mock.Mock()
        fake_cal.is_connected.return_value = True

        with app.test_request_context(), \
             mock.patch("server.friday_brain", fake_brain), \
             mock.patch("server.friday_calendar", fake_cal):
            prompt = "I'm not sure yet"
            result = server._cmd_calendar_add(prompt, prompt.lower())

        assert result is not None
        assert "try the full request again" in result.get_json()["response"].lower()
        assert server._pending_calendar_add == {}

    def test_cancel_trigger_clears_pending_without_calling_the_model(self, app):
        server._pending_calendar_add = {
            "context": "schedule a meeting", "expires": time_module.time() + 300,
        }
        fake_brain = mock.Mock()

        with app.test_request_context(), mock.patch("server.friday_brain", fake_brain):
            prompt = "never mind"
            result = server._cmd_calendar_add(prompt, prompt.lower())

        assert result is not None
        assert "scrapped" in result.get_json()["response"].lower()
        assert server._pending_calendar_add == {}
        fake_brain.think.assert_not_called()

    def test_expired_pending_is_treated_as_not_pending(self, app):
        server._pending_calendar_add = {
            "context": "schedule a meeting", "expires": time_module.time() - 1,
        }
        with app.test_request_context():
            result = server._cmd_calendar_add("what's for dinner", "what's for dinner")

        assert result is None
        assert server._pending_calendar_add == {}


class TestSpotifyDoesNotSwallowSpecificCommands:
    """Confirmed live on a real device: "Put on my calendar September 1st
    Highschool Starts" came back "Spotify not authenticated". "put on" is
    a SPOTIFY_PLAY_TRIGGERS entry and a substring of "put on my calendar"
    / "put on my list", and _cmd_spotify_play runs well before both
    _cmd_calendar_add and _cmd_task_add in command()'s dispatch chain, so
    the vaguer music trigger matched first and tried to play "my calendar
    september 1st ..." as a track.

    Tested at the dispatcher level (does _cmd_spotify_play decline?)
    rather than end-to-end, because that's exactly where the bug was --
    both handlers were individually correct.
    """

    def test_the_exact_phrase_from_the_bug_report_is_not_a_music_request(self, app):
        prompt = "Put on my calendar September 1st Highschool Starts"
        with app.test_request_context(), \
             mock.patch("server.friday_spotify", mock.Mock()):
            result = server._cmd_spotify_play(prompt, prompt.lower())

        assert result is None, "Spotify swallowed a calendar request"

    def test_adding_to_a_list_is_not_a_music_request(self, app):
        """Broken the same way and never reported -- "put on my list" is
        also shadowed by "put on"."""
        prompt = "put on my list pick up milk"
        with app.test_request_context(), \
             mock.patch("server.friday_spotify", mock.Mock()):
            result = server._cmd_spotify_play(prompt, prompt.lower())

        assert result is None, "Spotify swallowed a task request"

    def test_a_genuine_music_request_still_plays(self, app):
        """The guard must not cost Spotify its actual trigger."""
        fake_spotify = mock.Mock()
        fake_spotify.play.return_value = {
            "playing": True, "track": "Back In Black", "artist": "AC/DC",
        }

        prompt = "put on some AC/DC"
        with app.test_request_context(), \
             mock.patch("server.friday_spotify", fake_spotify):
            result = server._cmd_spotify_play(prompt, prompt.lower())

        assert result is not None
        assert "Back In Black" in result.get_json()["response"]

    def test_the_shadow_list_is_derived_not_hardcoded(self):
        """Guards the self-maintaining property: a future "put on my X"
        trigger added to either list should be protected automatically,
        without anyone remembering this collision exists."""
        assert "put on my calendar" in server._SPOTIFY_SHADOWED_TRIGGERS
        assert "put on my list" in server._SPOTIFY_SHADOWED_TRIGGERS
        # Only genuinely-shadowed phrases, not the whole trigger lists.
        assert "add task" not in server._SPOTIFY_SHADOWED_TRIGGERS
