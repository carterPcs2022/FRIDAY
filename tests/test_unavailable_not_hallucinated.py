"""tests/test_unavailable_not_hallucinated.py — an unavailable feature
must say so, not hand the question to the model.

Twenty-five handlers gate their trigger check on `and <service>`, so
when that service didn't load they return None, the request falls
through the whole chain, and the conversational model answers instead --
with no idea what FRIDAY can actually do. That produced the two worst
answers of this branch, in opposite directions:

  "Can you read my Gmail"  -> "I'm not able to access your Gmail
                              account" (IMAP was working fine)
  "run a self repair"      -> "Self repair initiated, boss." (nothing
                              ran; SELF_REPAIR_OK was False, and the
                              321ms round trip with the model's badge on
                              it gave it away)

The second is the more dangerous shape: the boss believes a diagnostic
ran. "That isn't available right now" is a worse answer than doing the
thing and a far better one than pretending to.
"""
import re
from pathlib import Path
from unittest import mock

import pytest

import server
import core.app_state as app_state


def _all_services():
    src = Path(app_state.__file__).read_text()
    return set(re.findall(r"^\s*(\w+)\s*=\s*None$", src, re.M))


@pytest.fixture
def stubbed(monkeypatch):
    """Everything available, lockdown open, security off -- so a test can
    take exactly one service away and attribute the result to that."""
    for name in _all_services():
        monkeypatch.setattr(server, name, mock.Mock(), raising=False)

    brain = mock.Mock()
    brain.think.return_value = {
        "response": "Sure boss, I've taken care of that!",  # the improvisation
        "model": "llm", "ms": 100,
    }
    brain.classify.return_value = "fast"
    monkeypatch.setattr(server, "friday_brain", brain, raising=False)
    monkeypatch.setattr(server, "suit_lockdown", mock.Mock(is_locked=lambda: False), raising=False)
    monkeypatch.setattr(server, "SECURITY_OK", False, raising=False)
    monkeypatch.setattr(server, "VOICE_OK", False, raising=False)
    monkeypatch.setattr(server, "_pending_calendar_add", {}, raising=False)
    monkeypatch.setattr(server, "_pending_compose_send", {}, raising=False)
    return brain


class TestSelfRepair:
    """The reported case, verbatim."""

    def test_it_says_it_cannot_run_rather_than_claiming_it_did(self, app, stubbed, monkeypatch):
        monkeypatch.setattr(server, "SELF_REPAIR_OK", False)
        with app.test_request_context():
            body = server._handle_prompt("run a self repair").get_json()

        assert body["mode"] == "self_repair"
        assert "isn't loaded" in body["response"]
        # The exact failure: the model must not have been asked.
        assert "initiated" not in body["response"].lower()
        stubbed.think.assert_not_called()

    def test_a_working_self_repair_is_untouched(self, app, stubbed, monkeypatch):
        monkeypatch.setattr(server, "SELF_REPAIR_OK", True)
        sr = mock.Mock()
        sr.attempt_repair.return_value = {"status": "nothing_to_repair"}
        monkeypatch.setattr(server, "self_repair", sr)

        with app.test_request_context():
            body = server._handle_prompt("run a self repair").get_json()

        assert "every test passes" in body["response"]


class TestTheGeneralGuard:
    """Covers the other 24 handlers with the same shape, without needing
    a case per handler."""

    @pytest.mark.parametrize("prompt,service,feature", [
        ("check my email", "friday_gmail", "reading your inbox"),
        ("triage my inbox", "friday_gmail", "inbox triage"),
        ("my medicine schedule", "medicine_tracker", "your medication schedule"),
        ("what are my goals", "goals", "goals"),
        ("log today: it was long", "journal", "your journal"),
    ])
    def test_a_downed_service_is_reported_not_improvised(
        self, app, stubbed, monkeypatch, prompt, service, feature
    ):
        monkeypatch.setattr(server, service, None, raising=False)
        with app.test_request_context():
            body = server._handle_prompt(prompt).get_json()

        assert body["mode"] == "unavailable", (
            f"{prompt!r} fell through to the model with {service} down -- "
            f"it will invent an answer"
        )
        assert feature in body["response"]
        assert "taken care of" not in body["response"], "the model answered anyway"

    def test_ordinary_conversation_is_not_hijacked(self, app, stubbed):
        """The guard must stay quiet on anything that isn't clearly a
        feature request -- claiming a system is unavailable when the boss
        was just talking is its own wrong answer."""
        with app.test_request_context():
            body = server._handle_prompt("what do you think about the weather lately").get_json()

        assert body["mode"] != "unavailable"


class TestFeatureNaming:

    def test_the_most_specific_match_wins(self):
        """"put on my calendar" must name the calendar, not Spotify --
        both match, and the vaguer one would be actively misleading."""
        assert server._matched_but_unavailable(
            "put on my calendar dentist on september 1st"
        ) == "adding a calendar event"

    def test_an_unrelated_message_names_nothing(self):
        assert server._matched_but_unavailable("how are you doing today") is None

    def test_every_named_trigger_list_actually_exists(self):
        """A renamed trigger list would silently drop its feature from
        the guard, quietly restoring the fall-through for it."""
        missing = [
            name for name in server._FEATURE_TRIGGERS
            if not isinstance(getattr(server, name, None), list)
        ]
        assert not missing, f"_FEATURE_TRIGGERS names non-existent lists: {missing}"
