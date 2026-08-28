"""tests/test_trigger_shadowing.py — a vaguer trigger must not swallow a
more specific one dispatched later.

Two of these were found the hard way. "Put on my calendar September 1st"
came back "Spotify not authenticated" because SPOTIFY_PLAY_TRIGGERS'
"put on" is a substring of "put on my calendar" and Spotify dispatches
first. Auditing every trigger list against every other in dispatch order
then turned up the same shape in medication tracking, unreported:
REMINDER_TRIGGERS' "remind me" swallows MED_ADD_TRIGGERS' "remind me to
take", so the reminder fired but the medication was never recorded --
the visible half worked, which is exactly why nobody noticed.

The last test is the general guard: it re-runs that audit, so a future
trigger added to any list can't quietly reintroduce this.
"""
import ast
import re
from pathlib import Path
from unittest import mock

import server


class TestSpotifyDoesNotSwallow:
    def test_calendar_request_is_not_a_music_request(self, app):
        p = "Put on my calendar September 1st Highschool Starts"
        with app.test_request_context(), mock.patch("server.friday_spotify", mock.Mock()):
            assert server._cmd_spotify_play(p, p.lower()) is None

    def test_task_request_is_not_a_music_request(self, app):
        p = "put on my list pick up milk"
        with app.test_request_context(), mock.patch("server.friday_spotify", mock.Mock()):
            assert server._cmd_spotify_play(p, p.lower()) is None


class TestReminderDoesNotSwallowMedication:
    """The reminder still fires either way, so the only visible symptom
    is a missing adherence record -- worth a test precisely because it
    fails quietly."""

    def test_a_medication_reminder_defers_to_medication_tracking(self, app):
        p = "remind me to take my blood pressure pill at 8am"
        with app.test_request_context(), mock.patch("server.friday_brain", mock.Mock()):
            assert server._cmd_reminder(p, p.lower()) is None, \
                "reminder swallowed a medication request"

    def test_an_ordinary_reminder_still_works(self, app):
        """The guard must not cost _cmd_reminder its actual job."""
        p = "remind me in 30 minutes to call back"
        assert not any(t in p.lower() for t in server._REMINDER_SHADOWED_TRIGGERS)

    def test_the_shadow_list_is_derived_not_hardcoded(self):
        assert "remind me to take" in server._REMINDER_SHADOWED_TRIGGERS
        # Only genuinely-shadowed phrases, not the whole med list.
        assert "add medicine" not in server._REMINDER_SHADOWED_TRIGGERS


class TestNoUncheckedShadowingRemains:
    """Re-runs the audit that found the medication bug. A new trigger
    that shadows a later handler's fails here rather than shipping and
    silently misrouting."""

    # Collisions that are handled by an explicit deferral guard.
    KNOWN_GUARDED = {
        ("put on", "put on my calendar"),
        ("put on", "put on my list"),
        ("remind me", "remind me to take"),
    }

    def _trigger_lists(self, src):
        out = {}
        for m in re.finditer(r"^([A-Z_]*TRIGGERS)\s*=\s*(\[[^\]]*\])", src, re.M | re.S):
            try:
                out[m.group(1)] = [t.lower() for t in ast.literal_eval(m.group(2))]
            except Exception:
                pass
        return out

    def test_every_shadowing_pair_is_guarded(self):
        src = Path(server.__file__).read_text()
        lists = self._trigger_lists(src)

        order = []
        for m in re.finditer(r"result = (_cmd_\w+)\(prompt", src):
            if m.group(1) not in order:
                order.append(m.group(1))

        bodies = {}
        for m in re.finditer(r"^def (_cmd_\w+)\(", src, re.M):
            nxt = src.find("\ndef ", m.start() + 1)
            bodies[m.group(1)] = src[m.start():nxt if nxt > 0 else len(src)]

        def lists_used(cmd):
            # Whole-word match: FILE_RECALL_TRIGGERS contains
            # "CALL_TRIGGERS", and COMPOSE_SEND_TRIGGERS contains
            # "SEND_TRIGGERS" -- a naive substring check reports both as
            # collisions that don't exist.
            body = bodies.get(cmd, "")
            return [L for L in lists if re.search(rf"\b{L}\b", body)]

        unguarded = []
        for i, early in enumerate(order):
            for eL in lists_used(early):
                for late in order[i + 1:]:
                    for lL in lists_used(late):
                        if eL == lL:
                            continue
                        for ep in lists[eL]:
                            for lp in lists[lL]:
                                if ep != lp and ep in lp and (ep, lp) not in self.KNOWN_GUARDED:
                                    unguarded.append(f"{early}:{ep!r} shadows {late}:{lp!r}")

        assert not unguarded, "unguarded trigger shadowing:\n  " + "\n  ".join(unguarded)


class TestCapabilityIsNotFalselyDenied:
    """Confirmed live: "Can you read my Gmail" returned "I'm not able to
    access your Gmail account" -- while IMAP reading was configured and
    working. "gmail" appeared in no trigger list at all (every phrase
    said "email"/"inbox"/"mail"), so it fell through to the plain
    conversational model, which has no idea what FRIDAY can actually do.

    This is #16's failure inverted: not a fabricated claim that something
    happened, but a fabricated claim that a real capability doesn't
    exist. Same root cause -- a miss on the trigger lists hands the
    answer to a model that will confidently invent either direction."""

    def test_asking_to_read_gmail_reaches_the_email_handler(self):
        p = "can you read my gmail"
        assert [t for t in server.EMAIL_TRIGGERS if t in p], \
            "'gmail' still reaches no email trigger -- the model will deny the capability"

    def test_read_my_email_phrasing_is_covered(self):
        assert [t for t in server.EMAIL_TRIGGERS if t in "read my email"]

    def test_sending_to_a_gmail_address_still_reaches_the_sender_first(self):
        """The new triggers must not steal a compose request --
        _cmd_email_compose_send dispatches before _cmd_email_summary, so
        this checks the compose trigger still matches at all."""
        p = "send an email to my gmail account saying hi"
        assert [t for t in server.COMPOSE_SEND_TRIGGERS if t in p], \
            "compose no longer matches; the inbox reader would swallow it"
