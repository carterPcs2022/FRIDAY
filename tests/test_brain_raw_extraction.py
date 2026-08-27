"""tests/test_brain_raw_extraction.py — think(raw=True), the mode
structured-extraction callers need.

Confirmed live, and the actual reason every "put on my calendar ..."
request failed: think()'s pipeline is built to produce something
*speakable*, and every stage of that corrupts JSON. The extraction
prompt quotes the boss's own words back, so "Extract a calendar event
from: Put on my calendar September 1st ..." contains "my calendar",
matched _instant_response()'s calendar guard, and returned the canned
"Your calendar isn't connected yet, boss." -- the model was never called
at all, and the caller got a sentence where it expected JSON.

Three more stages would have broken it even with that guard passed:
_clean() deletes fenced code blocks outright, the voice-mode max_chars
cap truncates mid-string, and FRIDAY_PERSONALITY asks for warm
conversational replies.
"""
from unittest import mock

import pytest

import core.friday_brain as brain_mod
from core.friday_brain import friday_brain


EXTRACTION_PROMPT = (
    "Extract a calendar event from: Put on my calendar September 1st Highschool Starts\n"
    'Reply as JSON: {"title": str, "start": str, "end": str}'
)


@pytest.fixture
def fake_llm(monkeypatch):
    """Stands in for the provider cascade so these test think()'s own
    pipeline, not the network."""
    calls = {}

    def _call(messages, system, model=None):
        calls["system"] = system
        calls["messages"] = messages
        return {"content": calls.get("reply", '{"title": "X"}'),
                "model": "fake", "provider": "fake"}

    monkeypatch.setattr(brain_mod, "GROQ_API_KEY", "fake-key")
    monkeypatch.setattr(friday_brain, "_call_groq", _call)
    friday_brain._response_cache.clear()
    return calls


class TestInstantResponseIsBypassed:
    """The bug that actually broke calendar adds."""

    def test_the_guard_still_fires_for_a_real_question(self):
        assert friday_brain._instant_response("what's on my calendar") is not None

    def test_an_extraction_prompt_is_intercepted_without_raw(self):
        """Documents the trap: the prompt quotes the boss, so it trips a
        keyword guard meant for what the boss actually says."""
        assert friday_brain._instant_response(EXTRACTION_PROMPT) is not None

    def test_raw_reaches_the_model_instead_of_the_canned_reply(self, fake_llm):
        fake_llm["reply"] = '{"title": "Highschool Starts", "start": "2026-09-01", "end": "2026-09-01"}'
        out = friday_brain.think(EXTRACTION_PROMPT, raw=True)

        assert out["model"] == "fake", "instant-response short-circuited a raw call"
        assert "isn't connected" not in out["response"]
        assert '"title"' in out["response"]


class TestOutputIsNotMangled:

    def test_fenced_json_survives(self, fake_llm):
        """_clean() deletes ```...``` blocks entirely -- a fenced reply
        would arrive as an empty string."""
        fake_llm["reply"] = '```json\n{"title": "X", "start": "2026-09-01"}\n```'
        out = friday_brain.think("extract something", raw=True)

        assert '"title"' in out["response"]

    def test_long_json_is_not_truncated(self, fake_llm):
        """The voice max_chars cap (400 by default) would cut a longer
        extraction mid-string and make it unparseable."""
        import json
        payload = json.dumps({"title": "T" * 600, "start": "2026-09-01", "end": "2026-09-01"})
        fake_llm["reply"] = payload

        out = friday_brain.think("extract something", raw=True)

        assert out["response"] == payload
        assert json.loads(out["response"])["title"] == "T" * 600

    def test_markdown_emphasis_is_left_alone(self, fake_llm):
        """_clean() strips * characters, which would corrupt a JSON
        string value that legitimately contains them."""
        fake_llm["reply"] = '{"title": "*Important* meeting"}'
        out = friday_brain.think("extract something", raw=True)

        import json
        assert json.loads(out["response"])["title"] == "*Important* meeting"


class TestSystemPrompt:

    def test_raw_uses_the_extraction_prompt_not_the_personality(self, fake_llm):
        friday_brain.think("extract something", raw=True)
        assert fake_llm["system"] == brain_mod.EXTRACTION_SYSTEM

    def test_normal_calls_still_use_the_personality(self, fake_llm):
        friday_brain.think("how's the suit looking", raw=False)
        assert fake_llm["system"] != brain_mod.EXTRACTION_SYSTEM


class TestDefaultBehaviorIsUnchanged:
    """raw defaults to False so no existing caller shifts underfoot."""

    def test_a_normal_call_still_gets_the_canned_instant_reply(self):
        out = friday_brain.think("thanks")
        assert out["model"] == "instant"

    def test_a_normal_call_still_cleans_fences(self, fake_llm):
        fake_llm["reply"] = "```json\n{\"a\": 1}\n```"
        out = friday_brain.think("something conversational", raw=False)
        assert "{" not in out["response"]


class TestCacheKeyingIsPerMode:
    def test_raw_and_normal_do_not_share_a_cache_slot(self, fake_llm):
        """Sharing one would serve a spoken sentence to a caller parsing
        JSON, or the reverse -- order-dependent and very hard to spot."""
        fake_llm["reply"] = '{"a": 1}'
        raw_out = friday_brain.think("same words", raw=True)

        fake_llm["reply"] = "Sure thing, boss."
        normal_out = friday_brain.think("same words", raw=False)

        assert raw_out["response"] == '{"a": 1}'
        assert normal_out["response"] == "Sure thing, boss."


class TestRealCallSitesUseRawMode:
    """The instant-response guard matches on keywords, and extraction
    prompts quote the boss's own words back -- so ordinary requests
    hijack FRIDAY's own internal prompt. Measured before the fix:
    "send an email ... saying thanks for the help" returned "Always.",
    "... saying good morning" returned "Morning, boss.", and "... asking
    what time the meeting is" returned the clock. Four of five realistic
    phrasings never reached the model."""

    @pytest.mark.parametrize("user_text,would_hijack", [
        ("send an email to jane@x.com saying thanks for the help", "Always."),
        ("send an email to bob@x.com saying good morning, see you at 9", "Morning"),
        ("send an email to sam@x.com asking what time the meeting is", "It's"),
        ("send an email to pat@x.com about any events this weekend", "calendar"),
    ])
    def test_email_extraction_reaches_the_model(self, fake_llm, user_text, would_hijack):
        import server
        fake_llm["reply"] = (
            '{"to": "x@y.com", "subject": "s", "body": "b", "attachment": null}'
        )
        fake_gmail = mock.Mock()
        fake_gmail.extract_address.return_value = "x@y.com"
        fake_gmail.send_email.return_value = {"ok": True, "to": "x@y.com", "subject": "s"}

        with server.app.test_request_context(), \
             mock.patch("server.friday_brain", friday_brain), \
             mock.patch("server.friday_gmail", fake_gmail):
            server._pending_compose_send = {}
            result = server._cmd_email_compose_send(user_text, user_text.lower())

        # The point: it actually sent, rather than the canned line
        # reaching the JSON parser and failing.
        assert result is not None
        fake_gmail.send_email.assert_called_once()

    def test_a_prompt_quoting_the_boss_would_still_trip_the_guard_unprotected(self):
        """Guards the reasoning itself: if _instant_response ever stops
        matching these, this fix is no longer load-bearing and the test
        above would pass for the wrong reason."""
        prompt = "From this: 'send an email to jane@x.com saying thanks'\nExtract who to email"
        assert friday_brain._instant_response(prompt) == "Always."
