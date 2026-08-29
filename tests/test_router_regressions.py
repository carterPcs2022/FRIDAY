"""tests/test_router_regressions.py — bugs caught live, pinned so they
cannot come back silently.

Every entry here traces to a real [route] or [verify] log line from
Render, pasted by the boss. Neither bug was caught by the unit suites
that already covered these modules -- core/tool_router.py's own tests
passed while the rewrite it produced was garbage, and
core/outcome_verify.py's own tests passed while it appended a hedge onto
an already-failed reply. Both bugs lived at the SEAM between two
individually well-tested pieces: the router's output feeding a handler,
that handler's output feeding verification. A unit test, by
construction, does not see a seam.

This file is deliberately not merged into test_tool_router.py or
test_outcome_verify.py. It exists to answer one question on its own,
readable without cross-referencing another file: "has a bug we already
found ever come back?"
"""
from unittest import mock

import pytest

from core import tool_router, outcome_verify as verify


class TestRouterRewriteRegressions:
    """core/tool_router.py, live 2026-08-29.

    Log line: [route] 'keep track of my knee physio' -> habit_log ->
    'logged my keep track of my knee physio'

    The capability was right; the rewrite echoed the entire request back
    as `detail` instead of just the subject, producing a string with the
    canonical phrase's own verb repeated inside it. Fixed by stripping
    known filler/verb prefixes and leading possessives in
    tool_router._clean_detail(), not by trusting the prompt alone --
    the model was already told to return "the subject only" and didn't.
    """

    def test_keep_track_of_my_knee_physio(self):
        assert tool_router.rephrase("habit_log", "keep track of my knee physio") \
            == "logged my knee physio"

    @pytest.mark.parametrize("tool,detail,expected", [
        ("task_add",   "i need to grab dog food",              "add to my list grab dog food"),
        ("med_taken",  "my vitamins",                           "i took my vitamins"),
        ("note",       '"the wifi password"',                   "note that the wifi password"),
        ("calendar_add", "dinner with sarah at 7",               "put on my calendar dinner with sarah at 7"),
    ])
    def test_other_details_from_the_same_test_session(self, tool, detail, expected):
        """Verified against the router the same night, alongside the bug
        above -- pinned together since they share the fix."""
        assert tool_router.rephrase(tool, detail) == expected


class TestVerificationHedgeRegressions:
    """core/outcome_verify.py + server.py's _verify_outcome, live
    2026-08-29.

    Log line (paraphrased from the HUD screenshot, Render doesn't log
    the full reply text): "pencil in dinner with sarah thursday at 7"
    hit a Google 400 creating the event, and the reply came back
    "Failed to create event: 400 I couldn't confirm it went through,
    though -- worth checking." -- a hedge appended onto a sentence that
    had already said it failed.

    Every non-success branch of _cmd_calendar_add, _cmd_email_send and
    _cmd_email_compose_send shares its mode with the success branch, so
    verification ran on all of them and found no id every time. Fixed by
    gating on outcome_verify.applies(), which checks for the artifact id
    BEFORE verify() is ever called, not just before the amend.
    """

    @pytest.fixture(autouse=True)
    def restore_registry(self):
        original = dict(verify._VERIFIERS)
        yield
        verify._VERIFIERS.clear()
        verify._VERIFIERS.update(original)

    def test_a_failed_calendar_create_keeps_its_own_message(self, app, monkeypatch):
        import server
        from flask import jsonify
        monkeypatch.setattr(verify, "_VERIFIERS", dict(verify._VERIFIERS))
        verify.register("calendar", "added that to your calendar", "event_id",
                        lambda p: {"state": "unknown", "detail": "network down"})

        with app.test_request_context():
            response = jsonify({"response": "Failed to create event: 400",
                                "mode": "calendar"})
            body = server._verify_outcome(response, None).get_json()

        assert body["response"] == "Failed to create event: 400"
        assert "confirm" not in body["response"].lower()

    @pytest.mark.parametrize("mode,text", [
        ("calendar", "Scrapped it, boss."),
        ("calendar", "Your calendar isn't connected yet, boss."),
        ("calendar", "Wasn't sure what to schedule there, boss — try again with a date?"),
        ("email_send", "Couldn't send that, boss — no draft pending."),
        ("email_compose_send", "Who's it going to, and what should it say, boss?"),
    ])
    def test_other_no_op_and_failure_replies_from_the_same_family(self, app, mode, text):
        """None of these ever produce an id, and none were reported
        wrong on their own -- but they share the exact mechanism as the
        bug above, so they're pinned alongside it."""
        import server
        from flask import jsonify
        with app.test_request_context():
            response = jsonify({"response": text, "mode": mode})
            body = server._verify_outcome(response, None).get_json()

        assert body["response"] == text
        assert "verified" not in body


class TestRouterSelectionRegressions:
    """core/tool_router.py's _SYSTEM prompt, live 2026-08-29.

    "i owe sarah a reply at some point" routed to email_draft. It
    contains no trigger phrase for anything (checked directly against
    every *_TRIGGERS list) -- this was purely the selection model
    reading "reply" and "sarah" as a request to draft one, when the
    sentence actually describes an obligation, not an instruction.

    Unlike every other regression in this file, this one is NOT
    deterministically fixed. There is no code path to correct -- the
    router asked a model to judge intent, and it judged wrong. What
    changed is the prompt: a rule plus a worked negative example
    targeting this exact shape (a first-person statement of what the
    boss owes someone, sharing vocabulary with a capability's
    description). That reduces the chance of a repeat; it cannot
    guarantee one the way a code fix can. This test asserts the mitigation
    is actually present in the prompt sent to the model -- it cannot
    assert the model won't still get a differently-worded version of the
    same confusion wrong. That only gets checked by trying it live again.
    """

    def test_the_obligation_vs_request_guidance_is_in_the_prompt(self):
        assert "owe" in tool_router._SYSTEM
        assert "obligation" in tool_router._SYSTEM

    def test_the_exact_live_phrase_matches_no_trigger(self):
        """Confirms this could only ever have reached email_draft via
        the router's own judgment, not a trigger collision -- so a
        prompt fix is the right kind of fix, not a deflection from a
        code bug that actually exists somewhere else."""
        import server
        phrase = "i owe sarah a reply at some point"
        lists = {k: v for k, v in vars(server).items()
                 if k.endswith("_TRIGGERS") and isinstance(v, list)}
        hits = [t for v in lists.values() for t in v if t in phrase]
        assert not hits, f"phrase actually matches a real trigger: {hits}"
