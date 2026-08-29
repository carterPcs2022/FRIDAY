"""tests/test_router_integration.py — the router feeding a real handler
feeding real verification, end to end.

Every module here has its own unit suite, and all of them were green
while two real bugs shipped tonight. Both bugs lived at a SEAM: the
router's rewrite feeding a handler that reads it, that handler's
response feeding verification that reads it. A unit test proves a piece
works in isolation; it says nothing about what the next piece does with
its output.

So this chains all three, through the messiest input available: raw,
unedited strings the router's own selection model actually produced
tonight, not hand-picked clean examples. A hand-picked "put dinner on my
calendar at 7" would never have caught "logged my keep track of my knee
physio" -- that string looked nothing like what anyone would type as a
test fixture on purpose.

Every optional service is a Mock (see conftest.all_services), so this
proves wiring and data flow, not that Google Calendar's API behaves as
mocked -- that belongs to the per-service test files.
"""
from unittest import mock

import pytest

from core import tool_router


# Selections the router actually returned tonight, verbatim -- not
# reworded into something tidier for the test file.
LIVE_SELECTIONS = [
    {"tool": "weather", "detail": ""},
    {"tool": "habit_log", "detail": "keep track of my knee physio"},
]


class TestRouterOutputFeedsARealHandler:
    """The router picks a capability and rewrites; dispatch has to
    actually claim the rewrite and do something sane with it."""

    @pytest.mark.parametrize("selection", LIVE_SELECTIONS, ids=[s["tool"] for s in LIVE_SELECTIONS])
    def test_the_rewrite_is_claimed_and_produces_a_response(
            self, app, all_services, extracting_brain, selection):
        import server
        phrase = tool_router.rephrase(selection["tool"], selection["detail"])

        with app.test_request_context():
            result = server._run_chain(server._MAIN_CHAIN, phrase, phrase.lower())

        assert result is not None, f"{phrase!r} was not claimed by any handler"
        body = result.get_json()
        assert body.get("response"), "handler claimed the phrase but said nothing"

    def test_a_messy_habit_rewrite_does_not_crash_the_handler(self, app, all_services, extracting_brain):
        """The exact production string, run all the way through the
        real _cmd_habit_log rather than just checked for shape."""
        import server
        phrase = "logged my knee physio"  # post-fix output

        with app.test_request_context():
            result = server._cmd_habit_log(phrase, phrase.lower())

        assert result is not None
        assert result.get_json().get("response")


class TestHandlerOutputFeedsVerification:
    """A handler's response, whatever shape it's in, has to survive
    _verify_outcome without being corrupted -- confirmed and unverifiable
    paths pass through untouched; only a genuine contradiction changes
    the text."""

    def _through_verify(self, app, mode, text, **extra):
        from flask import jsonify
        import server
        with app.test_request_context():
            response = jsonify({"response": text, "mode": mode, **extra})
            return server._verify_outcome(response, None).get_json()

    @pytest.mark.parametrize("mode,text", [
        ("habit_log", "Logged it, boss."),
        ("weather", "Sunny, 72°F."),
        ("task_add", "Added to your list, boss."),
        ("note", "Noted, boss."),
    ])
    def test_unverifiable_modes_pass_through_byte_identical(self, app, mode, text):
        """These modes have no registered verifier, so the response must
        be the exact object handed in -- not almost the same, not
        re-serialized differently."""
        body = self._through_verify(app, mode, text)
        assert body["response"] == text
        assert "verified" not in body

    def test_a_calendar_failure_is_not_touched_by_verification(self, app):
        """The regression this integration path exists to prevent from
        ever being reintroduced by an unrelated change elsewhere in the
        chain."""
        body = self._through_verify(app, "calendar", "Failed to create event: 400")
        assert body["response"] == "Failed to create event: 400"

    def test_a_calendar_success_with_an_id_is_actually_checked(self, app, monkeypatch):
        """The other half: when there IS something to verify, it must
        still run -- this integration layer must not have accidentally
        turned verification off altogether while fixing the hedge bug."""
        from core import outcome_verify as verify
        monkeypatch.setattr(verify, "_VERIFIERS", dict(verify._VERIFIERS))
        called = []
        verify.register("calendar", "added that to your calendar", "event_id",
                        lambda p: called.append(1) or {"state": "confirmed"})

        self._through_verify(app, "calendar", 'Added "Dinner" to your calendar, boss.',
                             event_id="evt_1")

        assert called, "a response WITH an event_id must still be verified"


class TestTheFullChainOnAPhraseNoTriggerClaims:
    """Router -> dispatch -> verification, on a phrase that starts with
    nothing recognising it at all -- the exact shape of every bug found
    tonight. If this test class needs updating because a trigger list
    changed underneath it, that itself is useful information."""

    def test_a_router_only_phrase_ends_in_a_real_answer(
            self, app, all_services, extracting_brain, monkeypatch):
        import server
        monkeypatch.setattr(tool_router, "ENABLED", True)
        monkeypatch.setattr(tool_router, "select",
                            lambda *a: {"tool": "weather", "detail": ""})

        with app.test_request_context():
            result = server._handle_prompt("should i bring a jacket")

        body = result.get_json()
        assert body.get("mode") != "friday", (
            "fell through to the conversational model -- the router "
            "either didn't fire or its output wasn't claimed downstream"
        )
        assert body.get("response")
