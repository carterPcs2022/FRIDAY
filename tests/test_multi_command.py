"""tests/test_multi_command.py — several requests in one message.

The dispatch chain is 56 sequential checks, each ending "if result is not
None: return result", so the first match won and returned. "run a self
repair, can you read my Gmail, and remind me to take my vitamins at 8am"
matched three handlers -- _cmd_self_repair, _cmd_email_summary and
_cmd_med_add -- ran the first, and silently dropped the other two. No
error, no mention that anything was skipped.

Splitting is done by the model, not by punctuation, and the tests below
pin both halves of why: "email Jane, Bob and Sam about the meeting" is
one request whose commas must survive, while the example above is three.
Everything uncertain falls back to today's single-request behavior --
treating one request as several would act on things the boss never
asked for, which is worse than the bug being fixed.
"""
import json
from unittest import mock

import pytest

import server


def _brain(split_reply=None, other='{"name": "x"}'):
    """Answers the split prompt with split_reply and anything else with
    `other`, so a test can drive the splitter without also having to
    satisfy every downstream handler."""
    def think(q, context="", emotion_context="", raw=False):
        if raw and "Split this message" in q:
            return {"response": split_reply, "model": "t", "ms": 1}
        return {"response": other, "model": "t", "ms": 1}

    b = mock.Mock()
    b.think.side_effect = think
    b.classify.return_value = "fast"
    return b


def _requests(*parts):
    return json.dumps({"requests": list(parts)})


class TestSplitting:

    def test_the_reported_message_splits_into_three(self):
        prompt = ("run a self repair, can you read my gmail, and remind me "
                  "to take my vitamins at 8am")
        brain = _brain(_requests("run a self repair", "can you read my gmail",
                                 "remind me to take my vitamins at 8am"))
        with mock.patch.object(server, "friday_brain", brain):
            assert len(server._split_commands(prompt)) == 3

    def test_a_plain_single_request_never_calls_the_model(self):
        """The common case must not pay for an extra round trip."""
        brain = _brain(_requests("a", "b"))
        with mock.patch.object(server, "friday_brain", brain):
            assert server._split_commands("check my email") == ["check my email"]
        brain.think.assert_not_called()

    def test_commas_inside_one_request_are_not_split(self):
        """A list of recipients is one request. This is the case that
        makes punctuation-based splitting unsafe -- the model is asked
        precisely so this stays intact."""
        prompt = "send an email to Jane, Bob and Sam about the meeting"
        brain = _brain(_requests(prompt))
        with mock.patch.object(server, "friday_brain", brain):
            assert server._split_commands(prompt) == [prompt]


class TestSplittingFailsClosed:
    """Every uncertain path returns [prompt] -- exactly today's
    behavior -- because acting on a request the boss didn't make is worse
    than the original bug."""

    def test_a_model_error_falls_back_to_one_request(self):
        brain = mock.Mock()
        brain.think.side_effect = RuntimeError("groq down")
        with mock.patch.object(server, "friday_brain", brain):
            assert server._split_commands("a, b and c") == ["a, b and c"]

    def test_an_unparseable_reply_falls_back(self):
        with mock.patch.object(server, "friday_brain", _brain("not json at all")):
            assert server._split_commands("a, b and c") == ["a, b and c"]

    def test_paraphrased_pieces_are_rejected(self):
        """A model that rewrites rather than splits would have FRIDAY
        acting on words the boss never said."""
        prompt = "check my email and add milk to my list"
        brain = _brain(_requests("read the inbox", "put milk on the shopping list"))
        with mock.patch.object(server, "friday_brain", brain):
            assert server._split_commands(prompt) == [prompt]

    def test_no_brain_falls_back(self):
        with mock.patch.object(server, "friday_brain", None):
            assert server._split_commands("a, b and c") == ["a, b and c"]


class TestRunningSegments:

    def test_every_segment_runs_and_all_results_come_back(self, app):
        calls = []

        def fake_handle(seg, allow_split=True):
            calls.append((seg, allow_split))
            return server.jsonify({"response": f"did {seg}", "mode": "test"})

        with app.test_request_context(), \
             mock.patch.object(server, "_handle_prompt", fake_handle), \
             mock.patch.object(server, "VOICE_OK", False):
            body = server._run_segments(["one", "two", "three"]).get_json()

        assert [c[0] for c in calls] == ["one", "two", "three"], "order not preserved"
        # A segment must never be split again -- that's how you'd get
        # unbounded recursion on a pathological message.
        assert all(c[1] is False for c in calls)
        for expected in ("did one", "did two", "did three"):
            assert expected in body["response"]
        assert body["mode"] == "multi"

    def test_one_failing_segment_does_not_abandon_the_rest(self, app):
        """The boss asked for all of them; stopping silently after the
        second is the same class of problem this feature fixes."""
        def fake_handle(seg, allow_split=True):
            if seg == "two":
                raise RuntimeError("boom")
            return server.jsonify({"response": f"did {seg}", "mode": "test"})

        with app.test_request_context(), \
             mock.patch.object(server, "_handle_prompt", fake_handle), \
             mock.patch.object(server, "VOICE_OK", False):
            body = server._run_segments(["one", "two", "three"]).get_json()

        assert "did one" in body["response"]
        assert "did three" in body["response"], "a later segment was skipped after a failure"
        assert "Couldn't do that one" in body["response"]

    def test_a_handler_returning_a_status_tuple_is_handled(self, app):
        """Several handlers return (response, status) rather than a bare
        response -- unpacking only the bare form would crash the run."""
        def fake_handle(seg, allow_split=True):
            return server.jsonify({"response": "blocked", "mode": "x"}), 403

        with app.test_request_context(), \
             mock.patch.object(server, "_handle_prompt", fake_handle), \
             mock.patch.object(server, "VOICE_OK", False):
            body = server._run_segments(["one"]).get_json()

        assert "blocked" in body["response"]


class TestTheSplitterIsActuallyWiredIn:
    """Added after a teeth check embarrassed the rest of this file:
    deleting the split call from _handle_prompt entirely -- i.e.
    restoring the original bug -- left every other test in here passing,
    because they all exercise _split_commands and _run_segments in
    isolation and never assert the two are connected. That is the same
    unit-vs-integration gap that let tonight's bugs ship past 351 green
    tests."""

    def test_a_multi_request_message_goes_down_the_multi_path(self, app):
        prompt = "check my email and add milk to my list"
        brain = _brain(_requests("check my email", "add milk to my list"))

        seen = []

        def fake_handle_segment(seg, allow_split=True):
            seen.append(seg)
            return server.jsonify({"response": f"did {seg}", "mode": "test"})

        with app.test_request_context(), \
             mock.patch.object(server, "friday_brain", brain), \
             mock.patch.object(server, "VOICE_OK", False), \
             mock.patch.object(server, "suit_lockdown", mock.Mock(is_locked=lambda: False)), \
             mock.patch.object(server, "SECURITY_OK", False), \
             mock.patch.object(server, "_run_segments",
                               lambda segs: server.jsonify({"response": "|".join(segs),
                                                            "mode": "multi"})):
            body = server._handle_prompt(prompt).get_json()

        assert body["mode"] == "multi", (
            "_handle_prompt did not route a multi-request message through the "
            "splitter -- the original bug is back"
        )
        assert body["response"] == "check my email|add milk to my list"

    def test_a_single_request_message_does_not_go_down_the_multi_path(self, app):
        """The guard in the other direction: ordinary messages must keep
        their own handler's mode, not become "multi"."""
        called = []
        with app.test_request_context(), \
             mock.patch.object(server, "friday_brain", _brain(_requests("check my email"))), \
             mock.patch.object(server, "suit_lockdown", mock.Mock(is_locked=lambda: False)), \
             mock.patch.object(server, "SECURITY_OK", False), \
             mock.patch.object(server, "_run_segments",
                               lambda segs: called.append(segs)):
            server._handle_prompt("check my email")

        assert not called, "a single request was sent down the multi-segment path"


class TestSingleRequestBehaviorIsUnchanged:
    def test_a_single_request_still_returns_its_own_mode(self, app):
        """Multi-command must not reshape the response for the ordinary
        case -- the HUD and every existing test read `mode`."""
        brain = _brain(_requests("check my email"))
        with app.test_request_context(), \
             mock.patch.object(server, "friday_brain", brain):
            segments = server._split_commands("check my email")
        assert segments == ["check my email"]
