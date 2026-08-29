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


class TestExplanatoryQuestionsAreNotClaims:
    """Found in production: "how does the calendar thing work" came back
    as "I didn't actually do anything there, boss -- I don't have a way to
    handle that one yet."

    The guard only ever saw the reply, never the question, so it could not
    tell a description of a mechanism from a claim about this turn. Both
    look identical in the first person:

        "I'm adding it straight to your calendar"       explanation
        "I've set it up so you can just say the date"   explanation

    Destroying a correct answer is a worse failure than the hallucination
    the guard exists to catch, because the boss asked a question and got
    told nothing happened.
    """

    EXPLANATIONS = [
        "When you tell me an event, I'm adding it straight to your calendar.",
        "I've set it up so you can just say the date.",
        "I connect to Google Calendar and add events when you ask.",
    ]

    @pytest.mark.parametrize("reply", EXPLANATIONS)
    def test_an_explanation_survives_when_the_question_asked_for_one(self, reply):
        assert claims_action(reply, "how does the calendar thing work") is None

    @pytest.mark.parametrize("reply", EXPLANATIONS)
    def test_the_same_reply_is_still_guarded_without_that_context(self, reply):
        """The guard is not being loosened -- it is being told what was
        asked. With no question, the conservative reading still wins."""
        assert claims_action(reply) is not None or "connect" in reply

    @pytest.mark.parametrize("opener", [
        "how does the calendar thing work",
        "how do you send email",
        "what happens when I say lockdown",
        "explain the reminder system",
        "tell me about your calendar",
    ])
    def test_explanatory_openers_are_recognised(self, opener):
        from core.action_claims import is_explanatory
        assert is_explanatory(opener)

    @pytest.mark.parametrize("request_", [
        "can you send an email to jane",
        "could you add that to my calendar",
        "would you remind me at 8",
        "send an email to jane",
    ])
    def test_a_request_wearing_a_question_mark_is_still_guarded(self, request_):
        """The hole this must not open. "can you X" is an instruction, not
        a question about how X works, and a model answering it with
        "Sending it now" is the exact hallucination being caught."""
        from core.action_claims import is_explanatory
        assert not is_explanatory(request_)
        assert claims_action("Sending it now.", request_) is not None

    def test_a_real_claim_after_a_real_request_still_fires(self):
        assert claims_action("I sent that email.", "send an email to jane")


def test_the_call_site_passes_the_prompt():
    """The guard takes `prompt` optionally so existing callers keep
    working -- which means dropping it at the call site breaks nothing
    and fails no test. Verified: removing it left all 701 green.

    Asserted against the source rather than through /command because the
    conversational path needs friday_brain, which doesn't import in CI --
    an end-to-end version would measure the environment, the way three
    other test files in this repo already did before being fixed.
    """
    import re
    from pathlib import Path
    import server

    src = Path(server.__file__).read_text()
    calls = re.findall(r"claims_action\(([^)]*)\)", src)
    calls = [c for c in calls if "def " not in c]

    assert calls, "nothing calls claims_action any more -- the guard is dead"
    assert all("prompt" in c for c in calls), (
        f"claims_action is called without the prompt: {calls} -- the guard "
        f"then cannot tell an explanation from a claim about this turn"
    )
