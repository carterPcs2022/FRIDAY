"""tests/test_email_compose_send.py — _cmd_email_compose_send's pending-
reply state. The bug this exists to catch: a boss's reply that answers
FRIDAY's own "who's it going to, and what should it say" question
carries none of COMPOSE_SEND_TRIGGERS' phrases, so without this state it
falls through every dispatcher and lands on the plain conversational
model -- which happily describes "sending" the email in prose without
ever calling send_email(). Confirmed happening for real (a live /hud
screenshot showed exactly this: a generic-sounding "On it, boss..."
reply that never matched send_email()'s actual success template) before
this fix.

_cmd_calendar_add had the identical shape of a second bug: a pending
follow-up swallowing the very next message even when it had nothing to
do with the question being asked. Calendar's fix requires a date/time
signal in the reply; that doesn't transfer here since a genuine email
reply can legitimately be almost any text. What does transfer is
checking whether the message matches some OTHER handler's own trigger
phrase -- see _looks_like_someone_elses_request and
TestUnrelatedRequestsDuringPending below.
"""
from unittest import mock

import server


def _think(payload):
    return {"response": payload, "model": "test", "ms": 1}


class TestNewRequest:
    def test_no_trigger_and_nothing_pending_returns_none(self, app):
        with app.test_request_context():
            result = server._cmd_email_compose_send("what time is it", "what time is it")
        assert result is None

    def test_complete_extraction_sends_immediately(self, app):
        fake_brain = mock.Mock()
        fake_brain.think.return_value = _think(
            '{"to": "jane@x.com", "subject": "Hi", "body": "running late", "attachment": null}'
        )
        fake_gmail = mock.Mock()
        fake_gmail.extract_address.side_effect = lambda s: s if "@" in (s or "") else ""
        fake_gmail.send_email.return_value = {"ok": True, "to": "jane@x.com"}

        with app.test_request_context(), \
             mock.patch("server.friday_brain", fake_brain), \
             mock.patch("server.friday_gmail", fake_gmail):
            prompt = "send an email to jane@x.com saying running late"
            result = server._cmd_email_compose_send(prompt, prompt.lower())

        assert result is not None
        body = result.get_json()
        assert "Sent, boss" in body["response"]
        fake_gmail.send_email.assert_called_once()
        assert server._pending_compose_send == {}

    def test_incomplete_extraction_sets_pending_and_asks(self, app):
        fake_brain = mock.Mock()
        fake_brain.think.return_value = _think('{"to": "", "subject": "", "body": "", "attachment": null}')
        fake_gmail = mock.Mock()
        fake_gmail.extract_address.return_value = ""
        fake_gmail.find_email.return_value = None

        with app.test_request_context(), \
             mock.patch("server.friday_brain", fake_brain), \
             mock.patch("server.friday_gmail", fake_gmail), \
             mock.patch("server.friday_contacts", None):
            prompt = "send an email to my brother"
            result = server._cmd_email_compose_send(prompt, prompt.lower())

        assert result is not None
        body = result.get_json()
        assert "who's it going to" in body["response"].lower()
        fake_gmail.send_email.assert_not_called()
        assert server._pending_compose_send != {}
        assert "context" in server._pending_compose_send


class TestPendingReply:
    def test_trigger_less_reply_completes_and_actually_sends(self, app):
        """The exact bug: a follow-up reply with none of
        COMPOSE_SEND_TRIGGERS' phrases must still reach send_email(),
        not fall through to a fabricated "On it, boss" chat reply."""
        server._pending_compose_send = {
            "context": "send an email to my brother", "expires": __import__("time").time() + 300,
        }
        fake_brain = mock.Mock()
        fake_brain.think.return_value = _think(
            '{"to": "jane@x.com", "subject": "", "body": "running late", "attachment": null}'
        )
        fake_gmail = mock.Mock()
        fake_gmail.extract_address.side_effect = lambda s: s if "@" in (s or "") else ""
        fake_gmail.send_email.return_value = {"ok": True, "to": "jane@x.com"}

        with app.test_request_context(), \
             mock.patch("server.friday_brain", fake_brain), \
             mock.patch("server.friday_gmail", fake_gmail):
            prompt = "jane@x.com and tell her I'm running late"
            result = server._cmd_email_compose_send(prompt, prompt.lower())

        assert result is not None
        body = result.get_json()
        assert "Sent, boss" in body["response"]
        fake_gmail.send_email.assert_called_once()
        # The combined context (original ask + this reply), not the bare
        # reply alone, is what should have gone to extraction -- "jane@x.com"
        # only means anything next to "send an email to my brother".
        sent_prompt = fake_brain.think.call_args[0][0]
        assert "my brother" in sent_prompt
        assert "running late" in sent_prompt

    def test_second_miss_gives_up_instead_of_looping(self, app):
        server._pending_compose_send = {
            "context": "send an email to someone", "expires": __import__("time").time() + 300,
        }
        fake_brain = mock.Mock()
        fake_brain.think.return_value = _think('{"to": "", "subject": "", "body": "", "attachment": null}')
        fake_gmail = mock.Mock()
        fake_gmail.extract_address.return_value = ""
        fake_gmail.find_email.return_value = None

        with app.test_request_context(), \
             mock.patch("server.friday_brain", fake_brain), \
             mock.patch("server.friday_gmail", fake_gmail), \
             mock.patch("server.friday_contacts", None):
            prompt = "I don't know, whoever"
            result = server._cmd_email_compose_send(prompt, prompt.lower())

        assert result is not None
        body = result.get_json()
        assert "try the full request again" in body["response"].lower()
        # Cleared, not re-armed -- a second miss must not keep capturing
        # whatever the boss says next indefinitely.
        assert server._pending_compose_send == {}

    def test_cancel_trigger_clears_pending_without_calling_the_model(self, app):
        server._pending_compose_send = {
            "context": "send an email to my brother", "expires": __import__("time").time() + 300,
        }
        fake_brain = mock.Mock()

        with app.test_request_context(), mock.patch("server.friday_brain", fake_brain):
            prompt = "never mind"
            result = server._cmd_email_compose_send(prompt, prompt.lower())

        assert result is not None
        assert "scrapped" in result.get_json()["response"].lower()
        assert server._pending_compose_send == {}
        fake_brain.think.assert_not_called()

    def test_expired_pending_is_treated_as_not_pending(self, app):
        server._pending_compose_send = {
            "context": "send an email to my brother", "expires": __import__("time").time() - 1,
        }
        with app.test_request_context():
            result = server._cmd_email_compose_send("what's for dinner", "what's for dinner")

        # Expired and no trigger phrase in this prompt -> not this
        # dispatcher's concern, must fall through cleanly (None), not
        # get misread as an email reply.
        assert result is None
        assert server._pending_compose_send == {}

    def test_unrelated_message_with_live_pending_does_not_silently_send(self, app):
        """A message that isn't answering the email question at all
        (still within the window) must not produce a real send from
        whatever the model guesses -- covered by the "empty strings
        rather than guessing" instruction, verified here via a extraction
        mock that (correctly, per that instruction) returns nothing."""
        server._pending_compose_send = {
            "context": "send an email to my brother", "expires": __import__("time").time() + 300,
        }
        fake_brain = mock.Mock()
        fake_brain.think.return_value = _think('{"to": "", "subject": "", "body": "", "attachment": null}')
        fake_gmail = mock.Mock()
        fake_gmail.extract_address.return_value = ""
        fake_gmail.find_email.return_value = None

        with app.test_request_context(), \
             mock.patch("server.friday_brain", fake_brain), \
             mock.patch("server.friday_gmail", fake_gmail), \
             mock.patch("server.friday_contacts", None):
            prompt = "what's for dinner tonight"
            result = server._cmd_email_compose_send(prompt, prompt.lower())

        assert result is not None
        fake_gmail.send_email.assert_not_called()


class TestUnrelatedRequestsDuringPending:
    """The same live incident shape as _cmd_calendar_add's: a request for
    a completely different capability arriving while a compose-send
    follow-up is pending must not be claimed by the email handler at
    all -- silently folding it into "who's it going to" is worse than
    any mechanical follow-up message could be."""

    def test_a_task_request_is_not_swallowed_by_pending_state(self, app):
        server._pending_compose_send = {
            "context": "send an email to my brother", "expires": __import__("time").time() + 300,
        }
        fake_brain = mock.Mock()

        with app.test_request_context(), mock.patch("server.friday_brain", fake_brain):
            prompt = "don't forget to call the dentist"
            result = server._cmd_email_compose_send(prompt, prompt.lower())

        assert result is None
        assert server._pending_compose_send == {}
        fake_brain.think.assert_not_called()

    def test_a_calendar_request_is_not_swallowed_by_pending_state(self, app):
        server._pending_compose_send = {
            "context": "send an email to my brother", "expires": __import__("time").time() + 300,
        }
        fake_brain = mock.Mock()

        with app.test_request_context(), mock.patch("server.friday_brain", fake_brain):
            prompt = "put on my calendar lunch at noon"
            result = server._cmd_email_compose_send(prompt, prompt.lower())

        assert result is None
        assert server._pending_compose_send == {}
        fake_brain.think.assert_not_called()

    def test_a_genuine_reply_that_happens_to_share_no_other_trigger_still_completes(self, app):
        """The guard must not cost compose-send its actual pending-reply
        behaviour -- a plain answer to "who's it going to" matches no
        other handler's trigger phrases and must still go through."""
        server._pending_compose_send = {
            "context": "send an email to my brother", "expires": __import__("time").time() + 300,
        }
        fake_brain = mock.Mock()
        fake_brain.think.return_value = _think(
            '{"to": "jane@x.com", "subject": "", "body": "running late", "attachment": null}'
        )
        fake_gmail = mock.Mock()
        fake_gmail.extract_address.side_effect = lambda s: s if "@" in (s or "") else ""
        fake_gmail.send_email.return_value = {"ok": True, "to": "jane@x.com"}

        with app.test_request_context(), \
             mock.patch("server.friday_brain", fake_brain), \
             mock.patch("server.friday_gmail", fake_gmail):
            prompt = "jane@x.com, tell her I'm running late"
            result = server._cmd_email_compose_send(prompt, prompt.lower())

        assert result is not None
        assert "Sent, boss" in result.get_json()["response"]

    def test_cancelling_still_wins_even_though_cancel_is_not_someone_elses_request(self, app):
        """Sanity check on the is_cancel-or-not-shadowed condition:
        cancelling must still cancel, not fall through as "unrelated"."""
        server._pending_compose_send = {
            "context": "send an email to my brother", "expires": __import__("time").time() + 300,
        }
        fake_brain = mock.Mock()

        with app.test_request_context(), mock.patch("server.friday_brain", fake_brain):
            prompt = "cancel that"
            result = server._cmd_email_compose_send(prompt, prompt.lower())

        assert result is not None
        assert "scrapped" in result.get_json()["response"].lower()
        assert server._pending_compose_send == {}
        fake_brain.think.assert_not_called()


class TestLooksLikeSomeoneElsesRequest:
    """server._looks_like_someone_elses_request -- the guard that decides
    whether a message pending on a compose-send follow-up actually
    belongs to some other handler instead."""

    def test_recognises_other_handlers_triggers(self):
        assert server._looks_like_someone_elses_request("don't forget to call the dentist")
        assert server._looks_like_someone_elses_request("put on my calendar lunch")
        assert server._looks_like_someone_elses_request("play some ac/dc")

    def test_does_not_fire_on_a_plausible_email_reply(self):
        assert not server._looks_like_someone_elses_request("jane@x.com, tell her i'm running late")
        assert not server._looks_like_someone_elses_request("my brother, running late")

    def test_ignores_its_own_triggers_and_cancel(self):
        """COMPOSE_SEND_TRIGGERS and CANCEL_TRIGGERS are excluded on
        purpose -- is_new_request and is_cancel already handle those
        cases, and treating them as "someone else's request" here would
        wrongly block a re-issued compose-send or a cancel."""
        assert not server._looks_like_someone_elses_request("send an email to jane")
        assert not server._looks_like_someone_elses_request("never mind")
