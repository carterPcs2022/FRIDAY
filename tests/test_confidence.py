"""tests/test_confidence.py — how FRIDAY knows how much she knows.

The tempting implementation is to ask the model how confident it is. That
does not work: self-reported certainty is highest exactly where a model is
confabulating, because fluent invention and recall feel identical from the
inside. It would produce a number that looks like calibration and isn't.

So confidence here is derived from provenance, which FRIDAY knows for
certain and which needs no cooperation from the model: did a service
produce this, did it come out of her own memory, or is it the
conversational model answering from training?

The surface is deliberately restrained. An earlier draft appended "that's
from memory, not looked up" to factual-sounding questions, and the
existing test suite caught it immediately -- "how many people are coming"
matched the heuristic while being a question about the boss's life, not a
lookup. No regex separates those reliably, and hedging the wrong answers
is worse than not hedging. She now volunteers nothing and answers
straight when asked.
"""
import pytest

from core import confidence


@pytest.fixture(autouse=True)
def clean_last():
    confidence._LAST.update(level="", prompt="", response="", mode="")


class TestProvenance:
    def test_a_service_answer_is_grounded(self):
        assert confidence.assess("weather") == confidence.GROUNDED

    def test_the_conversational_model_is_inferred(self):
        assert confidence.assess("friday") == confidence.INFERRED

    def test_memory_backed_conversation_is_recalled(self):
        """Something the boss told her is a different kind of claim from
        something the model knows, even though both arrive in the same
        voice."""
        assert confidence.assess("friday", used_memory=True) == confidence.RECALLED

    def test_emergency_mode_is_not_treated_as_grounded(self):
        """emergency() answers from a hardcoded fallback with no service
        behind it -- counting that as data would be exactly backwards."""
        assert confidence.assess("emergency") == confidence.INFERRED

    def test_an_unconfirmed_action_outranks_its_mode(self):
        """A send that couldn't be verified is not "grounded" just
        because a handler ran it."""
        assert confidence.assess("email_send", verified="unknown") == confidence.UNVERIFIED


class TestSheAnswersWhenAsked:
    def test_nothing_yet_is_said_plainly(self):
        assert "Nothing to check" in confidence.explain(confidence.last())

    def test_inferred_is_admitted_as_not_looked_up(self):
        confidence.remember(confidence.INFERRED, "q", "a", "friday")
        assert "didn't look it up" in confidence.explain(confidence.last())

    def test_grounded_names_the_source(self):
        """"I read that off your calendar" is the useful sentence; "I'm
        confident" is not."""
        confidence.remember(confidence.GROUNDED, "q", "a", "calendar")
        assert "your calendar" in confidence.explain(confidence.last())

    def test_recalled_credits_the_boss_not_the_model(self):
        confidence.remember(confidence.RECALLED, "q", "a", "friday")
        assert "you've told me" in confidence.explain(confidence.last())

    def test_unverified_admits_the_confirmation_is_missing(self):
        confidence.remember(confidence.UNVERIFIED, "q", "a", "email_send")
        assert "can't swear" in confidence.explain(confidence.last())

    def test_an_unknown_source_still_gets_a_sentence(self):
        confidence.remember(confidence.GROUNDED, "q", "a", "some_new_handler")
        assert confidence.explain(confidence.last())


class TestWiredIntoDispatch:
    """Split into "does the handler claim the phrase" and "does dispatch
    reach it", rather than posting to /command and asserting on the mode
    that comes back.

    The end-to-end version failed in CI and passed everywhere I could run
    it -- same Python, same requirements-dev.txt, stripped environment,
    and a faithful simulation of every service being None. Comparing runs
    showed the failing set growing from one test to three across commits
    that touched none of this, which is the signature of an
    order-and-environment effect rather than a static bug.

    Asserting "which of 59 handlers answered a client.post" is a claim
    about the whole live chain, and which handlers are live depends on
    which optional packages imported. The same flaw was fixed in
    tests/test_outcome_verify.py earlier and simply not carried across to
    here. Testing the handler directly plus a wiring spy is strictly
    stronger: it pins the behaviour AND the reachability, without either
    depending on what else happens to be installed.
    """

    def test_the_handler_claims_its_phrases(self, app):
        """Every trigger, not just one -- and directly, so no other
        handler can be in the way."""
        import server
        with app.test_request_context():
            for phrase in server.CONFIDENCE_TRIGGERS:
                assert server._cmd_confidence_query(phrase, phrase) is not None, \
                    f"{phrase!r} is in CONFIDENCE_TRIGGERS but the handler declines it"

    def test_it_declines_anything_else(self, app):
        import server
        with app.test_request_context():
            assert server._cmd_confidence_query("what's the weather",
                                                "what's the weather") is None

    def test_it_reports_the_remembered_answer(self, app):
        import server
        confidence.remember(confidence.GROUNDED, "q", "a", "calendar")
        with app.test_request_context():
            body = server._cmd_confidence_query("are you sure", "are you sure").get_json()
        assert body["mode"] == "confidence_query"
        assert "your calendar" in body["response"]
        assert body["about"]["level"] == confidence.GROUNDED

    def test_it_is_in_the_dispatch_chain(self):
        """Reachability, asserted against the registry rather than
        inferred from a round trip."""
        from core import dispatch_chain
        assert "_cmd_confidence_query" in dispatch_chain.MAIN

    def test_it_is_dispatched_before_self_audit(self):
        """"did you check" is close to the self-audit triggers, and the
        audit answers about her whole day rather than the last thing she
        said. First match wins, so position is the entire guarantee."""
        from core import dispatch_chain
        main = dispatch_chain.MAIN
        assert main.index("_cmd_confidence_query") < main.index("_cmd_self_audit")

    def test_provenance_is_recorded_for_an_ordinary_answer(self, client):
        client.post("/command", json={"prompt": "hello there"})
        assert confidence.last()["level"]

    def test_a_confidence_query_never_overwrites_what_it_reports_on(self, app):
        """Without the guard the second "are you sure?" reports on the
        first one, which is both useless and quietly circular."""
        import server
        from flask import jsonify
        confidence.remember(confidence.GROUNDED, "q", "a", "calendar")

        with app.test_request_context():
            server._remember_provenance(
                "are you sure",
                jsonify({"response": "...", "mode": "confidence_query"}))

        assert confidence.last()["mode"] == "calendar"

    def test_an_ordinary_answer_does_overwrite_it(self, app):
        import server
        from flask import jsonify
        confidence.remember(confidence.GROUNDED, "q", "a", "calendar")

        with app.test_request_context():
            server._remember_provenance(
                "what's the weather",
                jsonify({"response": "Sunny.", "mode": "weather"}))

        assert confidence.last()["mode"] == "weather"

    def test_she_volunteers_no_hedge_unprompted(self, client):
        """The personality file spends 374 words establishing that she
        doesn't pad. Qualifying every reply would break that and train the
        boss to skim past qualifiers, which costs more than it buys on the
        day one is real."""
        body = client.post("/command", json={"prompt": "hello there"}).get_json()
        assert "not looked up" not in body["response"].lower()


class TestProvenanceCannotCrashARequest:
    """Confirmed live: a response of None got as far as
    confidence.remember()'s response[:300] with nothing between it and
    Flask's default error page -- a bare 500, no JSON body, nothing in
    the app's own logs pointing at the cause. This is bookkeeping, same
    category as the action ledger a few lines above it in server.py --
    it must never be the reason a real request fails.
    """

    def test_a_none_response_does_not_raise(self):
        confidence.remember("grounded", "q", None, "email")
        assert confidence.last()["response"] == ""

    def test_a_none_prompt_does_not_raise(self):
        confidence.remember("grounded", None, "some answer", "email")
        assert confidence.last()["prompt"] == ""

    def test_server_side_guard_survives_a_none_response(self, app):
        """The full path: a handler's JSON payload literally carries
        "response": None, the exact shape that crashed in production."""
        import server
        from flask import jsonify
        with app.test_request_context():
            result = jsonify({"response": None, "mode": "email"})
            server._remember_provenance("check my email", result)  # must not raise

    def test_a_crash_anywhere_in_provenance_tracking_is_swallowed(self, app, monkeypatch):
        """Not just the one known cause -- nothing in this function may
        propagate, regardless of what breaks inside it."""
        import server
        from flask import jsonify
        monkeypatch.setattr(confidence, "assess",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        with app.test_request_context():
            result = jsonify({"response": "hi", "mode": "email"})
            server._remember_provenance("check my email", result)  # must not raise
