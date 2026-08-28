"""tests/test_action_claims.py — the conversational path must not claim
actions it cannot have taken.

If no handler in the dispatch chain claims a request, it reaches the
plain conversational model. That path performs no actions at all: no
tools, no service calls, no writes. So a reply from it asserting that
something happened is false by construction -- the code already knows
nothing was done, without needing to judge whether the model is confused.

Every hallucination found on this branch was this exact shape:

  "Sending an email..."          -> nothing sent            (#16)
  "Self repair initiated, boss." -> nothing ran
  "Boss, lockdown initiated."    -> nothing locked

Each was patched where it surfaced -- a guard for unavailable services,
another for near-miss safety commands. This catches the class instead of
the instances.

The hard part is not catching claims, it's *not* catching the honest
answers this branch spent the night adding. "I have not locked anything
down" and "I couldn't send that, boss" must sail through, or the guard
would suppress precisely the messages that fixed the problem.
"""
import pytest

from core.action_claims import claims_action


class TestRealHallucinationsAreCaught:
    """Verbatim from the live device."""

    @pytest.mark.parametrize("text", [
        "Boss, lockdown initiated.",
        "Self repair initiated, boss.",
        "On it, boss. Sending an email...",
    ])
    def test_the_observed_cases(self, text):
        assert claims_action(text) is not None, f"{text!r} would still reach the boss"


class TestOtherClaimShapes:
    @pytest.mark.parametrize("text", [
        "Done.",
        "Email sent.",
        "I sent the email, boss.",
        "I've added it to your list.",
        "Added it to your calendar, boss.",
        "Scheduled it for 3pm.",
        "Sending the reminder now.",
        "I just texted her.",
    ])
    def test_claims_are_flagged(self, text):
        assert claims_action(text) is not None


class TestHonestAnswersAreNotSuppressed:
    """The failure mode that would be worse than the bug: gagging the
    honest replies. Every one of these is a real message this branch
    added on purpose."""

    @pytest.mark.parametrize("text", [
        "I have not locked anything down, boss — that wasn't the phrase.",
        "I have not sent a mayday, boss — that wasn't the phrase.",
        "Couldn't send that, boss — timed out.",
        "Self-repair isn't loaded on this deploy, boss.",
        "I'd normally handle that (reading your inbox), boss, but that "
        "system isn't available right now — so I haven't done anything.",
        "Gmail sending isn't connected yet, boss — visit /friday/gmail/auth",
        "Wasn't sure what to schedule there, boss — try again with a date?",
    ])
    def test_honest_replies_pass_through(self, text):
        assert claims_action(text) is None, f"the guard would suppress: {text!r}"


class TestOrdinaryTalkIsNotFlagged:
    @pytest.mark.parametrize("text", [
        "All systems nominal, boss. Ready for action.",
        "Nine unread. One matters.",
        "That's a lot of people, boss.",
        "The math doesn't work, boss.",
        "Your calendar is clear tomorrow.",
        "I can send email if you give me an address.",
        "You should email her about it.",
        "What time is your flight, boss?",
        "Inbox is clear, boss.",
    ])
    def test_conversation_passes_through(self, text):
        assert claims_action(text) is None, f"false positive on: {text!r}"


class TestNegationWins:
    """Checked before anything else, deliberately -- a claim wrapped in a
    denial is the honest case, and flagging it would be backwards."""

    def test_negated_claims_are_not_flagged(self):
        assert claims_action("I didn't send it, boss.") is None
        assert claims_action("I haven't added that yet.") is None
        assert claims_action("I couldn't lock it down.") is None

    def test_empty_input_is_safe(self):
        assert claims_action("") is None
        assert claims_action(None) is None


class TestItIsActuallyWiredIn:
    """Tested separately on purpose. Earlier on this branch a teeth check
    showed the multi-command tests all passing with the feature deleted,
    because they only ever exercised the pieces in isolation and never
    asserted the two were connected. Same trap here."""

    def test_a_claiming_reply_is_replaced_before_it_reaches_the_boss(self, app, monkeypatch):
        from unittest import mock
        import server

        brain = mock.Mock()
        brain.classify.return_value = "fast"
        brain.think.return_value = {
            "response": "Boss, lockdown initiated.", "model": "llm", "ms": 200,
        }
        brain.voice_mode = "normal"

        monkeypatch.setattr(server, "friday_brain", brain)
        monkeypatch.setattr(server, "emotional_intel", None)
        monkeypatch.setattr(server, "VOICE_OK", False)
        monkeypatch.setattr(server, "COVERAGE_MODE", False)
        monkeypatch.setattr(server, "safe", lambda t: t)
        monkeypatch.setattr(server, "save_turn", lambda *a, **k: None)
        monkeypatch.setattr(server, "memory_hub", None, raising=False)

        with app.test_request_context():
            body = server._handle_prompt("do the thing with the stuff").get_json()

        assert "initiated" not in body["response"].lower(), (
            "the fabricated action claim reached the boss"
        )
        assert "didn't actually do anything" in body["response"]

    def test_an_ordinary_reply_is_left_alone(self, app, monkeypatch):
        """The guard must not rewrite normal conversation."""
        from unittest import mock
        import server

        brain = mock.Mock()
        brain.classify.return_value = "fast"
        brain.think.return_value = {
            "response": "That's a lot of people, boss.", "model": "llm", "ms": 200,
        }
        brain.voice_mode = "normal"

        monkeypatch.setattr(server, "friday_brain", brain)
        monkeypatch.setattr(server, "emotional_intel", None)
        monkeypatch.setattr(server, "VOICE_OK", False)
        monkeypatch.setattr(server, "COVERAGE_MODE", False)
        monkeypatch.setattr(server, "safe", lambda t: t)
        monkeypatch.setattr(server, "save_turn", lambda *a, **k: None)
        monkeypatch.setattr(server, "memory_hub", None, raising=False)

        with app.test_request_context():
            body = server._handle_prompt("how many people are coming").get_json()

        assert body["response"] == "That's a lot of people, boss."
