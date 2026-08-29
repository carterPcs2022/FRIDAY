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
    def test_provenance_is_recorded_for_an_ordinary_answer(self, client):
        client.post("/command", json={"prompt": "hello there"})
        assert confidence.last()["level"]

    def test_asking_reports_on_the_previous_answer(self, client):
        client.post("/command", json={"prompt": "hello there"})
        before = confidence.last()["level"]

        body = client.post("/command", json={"prompt": "are you sure"}).get_json()

        assert body["mode"] == "confidence_query"
        assert body["about"]["level"] == before

    def test_asking_twice_still_reports_the_original_answer(self, client):
        """Without the guard the second "are you sure?" reports on the
        first one, which is both useless and quietly circular."""
        client.post("/command", json={"prompt": "hello there"})
        client.post("/command", json={"prompt": "are you sure"})

        body = client.post("/command", json={"prompt": "how do you know"}).get_json()

        assert body["about"]["mode"] != "confidence_query"

    def test_she_volunteers_no_hedge_unprompted(self, client):
        """The personality file spends 374 words establishing that she
        doesn't pad. Qualifying every reply would break that and train the
        boss to skim past qualifiers, which costs more than it buys on the
        day one is real."""
        body = client.post("/command", json={"prompt": "hello there"}).get_json()
        assert "look" not in body["response"].lower()
        assert "not sure" not in body["response"].lower()

    def test_it_claims_the_phrase_before_self_audit(self, client):
        """"did you check" is close to the self-audit triggers, and the
        audit answers about her whole day rather than the last thing she
        said."""
        body = client.post("/command", json={"prompt": "did you check"}).get_json()
        assert body["mode"] == "confidence_query"
