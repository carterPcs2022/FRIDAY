"""tests/test_command_memory_integration.py — /command now builds its
context via core/memory_hub.py's unified recall() instead of the old
separate get_context_for() + get_wisdom_context() calls, which were
subsets of what memory_hub already covers. Conversation-turn recall
(core/friday_memory.recall()) is the one source memory_hub doesn't
have, so it stays as its own lookup alongside the hub.

PROTOCOLS_OK is force-False in every test below: server.py's background
JARVIS monitor thread (started at import time) sleeps 15s, then polls
real JARVIS/Groq/Anthropic reachability and sets friday_protocols.
range_level to DARK once none of them answer -- true for every CI/
sandbox run with no real credentials or network. Any test suite run
slow enough to cross that 15s mark makes every subsequent /command call
short-circuit through _cmd_dark_mode's emergency response before ever
reaching friday_brain, which is exactly what these tests are checking.
Pinning PROTOCOLS_OK False removes the dependency on that race entirely
regardless of how long the rest of the suite takes to run.
"""
from unittest import mock


def _post_command(client, prompt):
    return client.post("/command", json={"prompt": prompt})


class TestCommandUsesMemoryHub:
    def test_memory_hub_recall_is_consulted_and_folded_into_context(self, client):
        captured = {}

        def fake_think(prompt, context="", emotion_context=""):
            captured["context"] = context
            return {"response": "ok", "model": "test", "ms": 1}

        with mock.patch("server.friday_brain") as fb, \
             mock.patch("core.memory_hub.recall", return_value=[
                 {"text": "the staging server IP is 10.0.4.12", "source": "facts", "score": 3, "ts": None},
             ]) as recall_memory, \
             mock.patch("core.friday_memory.recall", return_value=[]), \
             mock.patch("server.emotional_intel", None), \
             mock.patch("server.PROTOCOLS_OK", False):
            fb.think.side_effect = fake_think
            fb.set_voice_mode = lambda *a, **k: None
            fb.voice_mode = "normal"
            fb.status.return_value = {"anthropic": True, "groq": True}

            _post_command(client, "what's the staging server IP")

        recall_memory.assert_called_once()
        assert recall_memory.call_args[0][0] == "what's the staging server IP"
        assert "staging server IP" in captured["context"]

    def test_conversation_recall_still_used_as_a_separate_source(self, client):
        captured = {}

        def fake_think(prompt, context="", emotion_context=""):
            captured["context"] = context
            return {"response": "ok", "model": "test", "ms": 1}

        with mock.patch("server.friday_brain") as fb, \
             mock.patch("core.memory_hub.recall", return_value=[]), \
             mock.patch("core.friday_memory.recall", return_value=["earlier: budget review -> done by Friday"]), \
             mock.patch("server.emotional_intel", None), \
             mock.patch("server.PROTOCOLS_OK", False):
            fb.think.side_effect = fake_think
            fb.set_voice_mode = lambda *a, **k: None
            fb.voice_mode = "normal"
            fb.status.return_value = {"anthropic": True, "groq": True}

            _post_command(client, "when's that budget review due")

        assert "Recent relevant" in captured["context"]
        assert "budget review" in captured["context"]

    def test_memory_hub_context_is_prepended_ahead_of_conversation_recall(self, client):
        """_build_messages() truncates context to its first 500 chars, so
        the query-specific, already-ranked memory_hub hits need to appear
        before the more generic conversation-recall text, not after."""
        captured = {}

        def fake_think(prompt, context="", emotion_context=""):
            captured["context"] = context
            return {"response": "ok", "model": "test", "ms": 1}

        with mock.patch("server.friday_brain") as fb, \
             mock.patch("core.memory_hub.recall", return_value=[
                 {"text": "MEMORY_HUB_MARKER", "source": "facts", "score": 5, "ts": None},
             ]), \
             mock.patch("core.friday_memory.recall", return_value=["CONVERSATION_MARKER"]), \
             mock.patch("server.emotional_intel", None), \
             mock.patch("server.PROTOCOLS_OK", False):
            fb.think.side_effect = fake_think
            fb.set_voice_mode = lambda *a, **k: None
            fb.voice_mode = "normal"
            fb.status.return_value = {"anthropic": True, "groq": True}

            _post_command(client, "anything")

        ctx = captured["context"]
        assert ctx.index("MEMORY_HUB_MARKER") < ctx.index("CONVERSATION_MARKER")

    def test_memory_hub_failure_does_not_break_command(self, client):
        """Same graceful-degradation contract as the old wisdom lookup:
        a broken memory source must not take the whole reply down."""
        with mock.patch("server.friday_brain") as fb, \
             mock.patch("core.memory_hub.recall", side_effect=RuntimeError("boom")), \
             mock.patch("core.friday_memory.recall", return_value=[]), \
             mock.patch("server.emotional_intel", None), \
             mock.patch("server.PROTOCOLS_OK", False):
            fb.think.return_value = {"response": "still works", "model": "test", "ms": 1}
            fb.set_voice_mode = lambda *a, **k: None
            fb.voice_mode = "normal"
            fb.status.return_value = {"anthropic": True, "groq": True}

            resp = _post_command(client, "anything")

        assert resp.status_code == 200
        assert resp.get_json().get("response") == "still works"
