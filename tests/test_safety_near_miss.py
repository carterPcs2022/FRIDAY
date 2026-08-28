"""tests/test_safety_near_miss.py — a safety command that only nearly
matches must take no action and say so.

Confirmed live: "lockdown" on its own matches none of LOCKDOWN_TRIGGERS
("lockdown now", "emergency lockdown", "lock the system", "suit
lockdown"), so it fell through the whole dispatch chain to the
conversational model, which answered "Boss, lockdown initiated." with its
own badge on it. Nothing locked.

That is the worst shape of the improvisation problem. A fabricated
"diagnostics ran" wastes time. A fabricated "you are locked down" means
believing the system is secured during precisely the situation where it
isn't.

The guard deliberately does NOT activate on a near miss. Lockdown is
one-way without ENDGAME_PASSPHRASE or a redeploy with RESET_LOCKDOWN,
and the word turns up in ordinary conversation about lockdown. Guessing
wrong in the activating direction is worse than asking for exact words.
"""
from unittest import mock

import pytest

import server


@pytest.fixture
def stubbed(monkeypatch):
    """The conversational model stands ready with exactly the wrong
    answer, so a fall-through would be unmistakable."""
    brain = mock.Mock()
    brain.think.return_value = {
        "response": "Boss, lockdown initiated.", "model": "llm", "ms": 232,
    }
    brain.classify.return_value = "fast"
    monkeypatch.setattr(server, "friday_brain", brain, raising=False)
    monkeypatch.setattr(server, "suit_lockdown", mock.Mock(is_locked=lambda: False), raising=False)
    monkeypatch.setattr(server, "SECURITY_OK", False, raising=False)
    monkeypatch.setattr(server, "VOICE_OK", False, raising=False)
    return brain


class TestNearMissTakesNoAction:

    @pytest.mark.parametrize("prompt", [
        "lockdown", "lock down", "lock it down", "secure the system",
    ])
    def test_lockdown_near_miss_does_not_lock_and_does_not_claim_to(
        self, app, stubbed, prompt
    ):
        with app.test_request_context():
            body = server._handle_prompt(prompt).get_json()

        assert body["mode"] == "safety_near_miss"
        assert body["acted"] is False
        assert "have not locked" in body["response"]
        assert "lockdown now" in body["response"], "it should name the exact phrase"
        # The specific live failure: the model must never get this.
        assert "initiated" not in body["response"].lower()
        stubbed.think.assert_not_called()

    def test_mayday_near_miss_does_not_broadcast(self, app, stubbed):
        with app.test_request_context():
            body = server._handle_prompt("mayday").get_json()

        assert body["acted"] is False
        assert "have not sent a mayday" in body["response"]
        stubbed.think.assert_not_called()


class TestExactTriggersStillWork:
    """The guard must not cost the real commands their triggers -- that
    would be a far worse failure than the one being fixed."""

    def test_the_exact_lockdown_phrase_still_locks(self, app, stubbed, monkeypatch):
        sl = mock.Mock(is_locked=lambda: False)
        monkeypatch.setattr(server, "suit_lockdown", sl)
        monkeypatch.setattr(server, "LOCKDOWN_OK", True)

        with app.test_request_context():
            body = server._handle_prompt("lockdown now").get_json()

        assert body["mode"] == "lockdown_activate"
        sl.activate.assert_called_once()

    def test_every_real_lockdown_trigger_still_reaches_the_handler(self, app, stubbed, monkeypatch):
        """Guards the ordering: the near-miss check runs after the real
        handlers, so no genuine trigger can be intercepted by it."""
        monkeypatch.setattr(server, "LOCKDOWN_OK", True)
        for trigger in server.LOCKDOWN_TRIGGERS:
            sl = mock.Mock(is_locked=lambda: False)
            monkeypatch.setattr(server, "suit_lockdown", sl)
            with app.test_request_context():
                body = server._handle_prompt(trigger).get_json()

            assert body["mode"] == "lockdown_activate", (
                f"{trigger!r} was intercepted by the near-miss guard"
            )
            sl.activate.assert_called_once()

    def test_the_mayday_phrase_still_fires(self, app, stubbed, monkeypatch):
        monkeypatch.setattr(server, "CHECKIN_OK", False)
        with app.test_request_context():
            body = server._handle_prompt(server.MAYDAY_PHRASE).get_json()

        assert body["mode"] == "MAYDAY"


class TestOrdinaryTalkIsNotHijacked:
    def test_an_unrelated_message_is_untouched(self, app, stubbed):
        with app.test_request_context():
            body = server._handle_prompt("what's the weather like").get_json()
        assert body["mode"] != "safety_near_miss"
