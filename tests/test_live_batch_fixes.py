"""tests/test_live_batch_fixes.py — bugs found running the 30-prompt live
test batch (LIVE_TEST_RESULTS.md) against the deployed app.

Five things this pins down:

1. "remind me to call the dentist tomorrow at 3" was hijacked by
   CALL_TRIGGERS' bare "call " -- _cmd_call_initiate dispatches well
   before _cmd_reminder, so the whole phrase got read as a contact name
   and FRIDAY claimed "Calling The Dentist Tomorrow At 3 now, boss."
   No reminder was ever set. Unlike the two shadowing bugs
   tests/test_trigger_shadowing.py guards (one trigger *list phrase*
   containing another), this is the boss's own sentence containing both
   triggers -- REMINDER_TRIGGERS' "remind me" isn't a substring of any
   CALL_TRIGGERS phrase, so that file's generic audit can't see this one.

2. "pause" always said "Pausing, boss." whatever friday_spotify.pause()
   actually returned -- confirmed live immediately after "play some
   AC/DC" honestly reported Spotify wasn't authenticated (nothing was
   playing), "pause" still claimed to have paused it.

3. "how am i doing on reading" (right after adding "Read 12 books this
   year" as a goal) reported on unrelated pre-existing goals instead,
   and the reply was truncated mid-word -- _cmd_goal_report always
   summarized every active goal in one "under 40 words" reply, so asking
   about a specific goal got buried in an unrelated dump squeezed for
   space.

4. "triage my inbox" on an empty inbox produced "Inbox triage complete,
   boss. .\nUrgent: none." -- an empty triage summary was spliced into
   the reply unconditionally.

5. "what have you done today" said "17 actions in the last day, all
   clean" while summary.counts.pending was 1 -- none of _cmd_self_audit's
   branches accounted for pending actions.
"""
from unittest import mock

import server


class TestCallDoesNotSwallowAReminder:
    def test_a_call_shaped_reminder_defers_to_the_reminder_handler(self, app):
        p = "remind me to call the dentist tomorrow at 3"
        with app.test_request_context():
            assert server._cmd_call_initiate(p, p.lower()) is None, \
                "call handler swallowed a reminder request"

    def test_an_ordinary_call_request_still_works(self, app):
        p = "call jane about the project"
        with app.test_request_context(), \
             mock.patch("server.relationships", None), \
             mock.patch("server.friday_brain", None):
            result = server._cmd_call_initiate(p, p.lower())
        assert result is not None
        payload = result.get_json()
        assert payload["mode"] == "call_initiation"
        assert payload["action"] == "call"


class TestSpotifyPauseReportsHonestly:
    def test_a_successful_pause_says_pausing(self, app):
        p = "pause"
        fake_spotify = mock.Mock()
        fake_spotify.pause.return_value = {"paused": True}
        with app.test_request_context(), mock.patch("server.friday_spotify", fake_spotify):
            result = server._cmd_spotify_stop(p, p.lower())
        assert result.get_json()["response"] == "Pausing, boss."

    def test_pausing_with_nothing_authenticated_is_not_fabricated(self, app):
        """Confirmed live: right after play() honestly said Spotify
        wasn't authenticated, pause() still claimed "Pausing, boss."
        with nothing actually playing."""
        p = "pause"
        fake_spotify = mock.Mock()
        fake_spotify.pause.return_value = {"error": "Not authenticated"}
        with app.test_request_context(), mock.patch("server.friday_spotify", fake_spotify):
            result = server._cmd_spotify_stop(p, p.lower())
        response = result.get_json()["response"]
        assert response == "Not authenticated"
        assert "pausing" not in response.lower()


class TestGoalReportAnswersTheNamedGoal:
    ACTIVE = [
        {"name": "Iron Man Suit", "sessions": 0, "last_worked": None},
        {"name": "Read 12 books this year", "sessions": 2, "last_worked": "2026-08-01T00:00:00"},
        {"name": "JARVIS V6", "sessions": 1, "last_worked": None},
    ]

    def test_matches_reading_to_the_read_12_books_goal(self, app):
        assert server._match_named_goal("how am i doing on reading", self.ACTIVE) \
            == self.ACTIVE[1]

    def test_no_match_when_nothing_overlaps(self, app):
        assert server._match_named_goal("goal report", self.ACTIVE) is None

    def test_matches_running_to_a_run_goal_despite_the_doubled_consonant(self, app):
        """"running" naively stemmed by stripping "-ing" leaves "runn",
        not "run" -- English doubles the final consonant before "-ing"
        and the stemmer doesn't undo that. Confirmed live: a goal named
        "run a 5k" wasn't matched by "how am i doing on running" at all
        until _match_named_goal compared stems by prefix instead of exact
        equality."""
        active = self.ACTIVE + [{"name": "run a 5k", "sessions": 0, "last_worked": None}]
        assert server._match_named_goal("how am i doing on running", active) \
            == active[-1]
        # The doubled-consonant fix must not make matching so loose that
        # the original, unrelated-word case starts colliding.
        assert server._match_named_goal("how am i doing on reading", active) \
            == self.ACTIVE[1]

    def test_named_goal_gets_its_own_focused_question_not_the_full_dump(self, app):
        p = "how am i doing on reading"
        fake_goals = mock.Mock()
        fake_goals.get_active_goals.return_value = self.ACTIVE
        fake_brain = mock.Mock()
        fake_brain.think.return_value = {"response": "Two sessions, boss, on track."}
        with app.test_request_context(), \
             mock.patch("server.goals", fake_goals), \
             mock.patch("server.friday_brain", fake_brain):
            result = server._cmd_goal_report(p, p.lower())
        assert result is not None
        query = fake_brain.think.call_args[0][0]
        assert "Read 12 books this year" in query
        assert "Iron Man Suit" not in query, \
            "asking about one goal still dumped every active goal into the prompt"


class TestInboxTriageHasNoStrayPunctuation:
    def test_an_empty_summary_does_not_leave_a_dangling_period(self, app):
        p = "triage my inbox"
        fake_gmail = mock.Mock()
        fake_gmail.smart_triage.return_value = {"summary": "", "categories": {}}
        with app.test_request_context(), mock.patch("server.friday_gmail", fake_gmail):
            result = server._cmd_email_triage(p, p.lower())
        response = result.get_json()["response"]
        assert " . " not in response and "boss. ." not in response
        assert response == "Inbox triage complete, boss.\nUrgent: none."

    def test_a_real_summary_is_still_included(self, app):
        p = "triage my inbox"
        fake_gmail = mock.Mock()
        fake_gmail.smart_triage.return_value = {
            "summary": "3 promos, 1 receipt", "categories": {"urgent": ["boss@example.com"]},
        }
        with app.test_request_context(), mock.patch("server.friday_gmail", fake_gmail):
            result = server._cmd_email_triage(p, p.lower())
        response = result.get_json()["response"]
        assert "3 promos, 1 receipt." in response
        assert "boss@example.com" in response


class TestSelfAuditNamesPendingActions:
    def test_all_clean_becomes_honest_about_a_pending_action(self, app):
        p = "what have you done today"
        fake_summary = {
            "counts": {"ok": 17, "failed": 0, "abandoned": 0, "pending": 1},
            "failing_capabilities": {},
        }
        with app.test_request_context(), \
             mock.patch("server.action_ledger.summary", return_value=fake_summary):
            result = server._cmd_self_audit(p, p.lower())
        response = result.get_json()["response"]
        assert "1 still in flight" in response

    def test_no_pending_actions_reads_exactly_as_before(self, app):
        p = "what have you done today"
        fake_summary = {
            "counts": {"ok": 5, "failed": 0, "abandoned": 0, "pending": 0},
            "failing_capabilities": {},
        }
        with app.test_request_context(), \
             mock.patch("server.action_ledger.summary", return_value=fake_summary):
            result = server._cmd_self_audit(p, p.lower())
        response = result.get_json()["response"]
        assert response == "5 actions in the last day, all clean."


class TestSafeCheckinToleratesADroppedApostrophe:
    def test_im_safe_without_the_apostrophe_still_matches(self):
        assert "im safe" in server.SAFE_TRIGGERS
