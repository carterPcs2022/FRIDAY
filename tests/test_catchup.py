"""tests/test_catchup.py — _cmd_catchup's parallel fetch must not be able
to take the whole server down.

Confirmed live, with a traceback. "anything important waiting for me"
routed to catchup, and one of its three parallel calls hung past its own
15-second timeout. as_completed(timeout=15) correctly gave up waiting --
but the surrounding "with ThreadPoolExecutor(...) as executor:" block's
own __exit__ calls shutdown(wait=True), which re-blocks on the exact
thread as_completed just gave up on. Gunicorn's own 30-second hard
worker timeout fired next, SIGKILLing the whole process -- a single
worker, so every other in-flight request died with it. Two unrelated
requests came back as 502 seconds later: not because they were slow, but
because the server was mid-crash-and-reboot when they landed.

CATCHUP_TIMEOUT is patched to milliseconds in these tests rather than
waited out for real seconds -- it's a named module constant specifically
so this file doesn't need to burn 15 real seconds per test.
"""
import concurrent.futures
import threading
import time
from unittest import mock

import pytest

import server


def _think(text):
    return {"response": text, "model": "test", "ms": 1}


@pytest.fixture(autouse=True)
def fast_timeout(monkeypatch):
    monkeypatch.setattr(server, "CATCHUP_TIMEOUT", 0.2)


class TestAHungCallDoesNotBlockTheResponse:
    """The actual production bug: as_completed gives up, but the request
    must not sit there anyway waiting for the same hung thread."""

    def test_the_request_returns_promptly_despite_a_hung_call(self, app):
        release = threading.Event()

        def hangs_past_the_timeout(*a, **k):
            release.wait(timeout=5)  # released at the end of the test
            return []

        fake_gmail = mock.Mock()
        fake_gmail.get_unread.side_effect = hangs_past_the_timeout
        fake_brain = mock.Mock()
        fake_brain.think.return_value = _think("Caught up, boss.")

        with app.test_request_context(), \
             mock.patch("server.friday_gmail", fake_gmail), \
             mock.patch("server.news_anchor", None), \
             mock.patch("server.relationships", None), \
             mock.patch("server.friday_calendar", None), \
             mock.patch("server.friday_brain", fake_brain), \
             mock.patch("server.get_tasks", return_value=[]):
            prompt = "what did i miss"
            started = time.monotonic()
            result = server._cmd_catchup(prompt, prompt.lower())
            elapsed = time.monotonic() - started

        release.set()  # let the background thread finish so it doesn't linger

        assert result is not None
        assert elapsed < 2.0, (
            f"took {elapsed:.1f}s -- the request waited on the hung call "
            f"instead of returning once CATCHUP_TIMEOUT fired"
        )

    def test_data_from_the_calls_that_finished_in_time_is_still_used(self, app):
        """The fix must not turn a partial success into total silence --
        the two calls that DID finish belong in the brief."""
        release = threading.Event()

        def hangs(*a, **k):
            release.wait(timeout=5)
            return []

        fake_gmail = mock.Mock()
        fake_gmail.get_unread.side_effect = hangs
        fake_news = mock.Mock()
        fake_news.morning_brief.return_value = "Quiet news day."
        fake_brain = mock.Mock()
        fake_brain.think.return_value = _think("Caught up, boss.")

        with app.test_request_context(), \
             mock.patch("server.friday_gmail", fake_gmail), \
             mock.patch("server.news_anchor", fake_news), \
             mock.patch("server.relationships", None), \
             mock.patch("server.friday_calendar", None), \
             mock.patch("server.friday_brain", fake_brain), \
             mock.patch("server.get_tasks", return_value=[]):
            prompt = "what did i miss"
            server._cmd_catchup(prompt, prompt.lower())

        release.set()

        sent = fake_brain.think.call_args[0][0]
        assert "Quiet news day" in sent

    def test_the_executor_is_not_joined_on_the_way_out(self, app):
        """The mechanism, asserted directly rather than only inferred
        from timing: shutdown must be called wait=False, or the fix is
        just moving the same block somewhere else."""
        captured = {}
        real_shutdown = concurrent.futures.ThreadPoolExecutor.shutdown

        def spy_shutdown(self, *a, **k):
            captured["wait"] = k.get("wait", a[0] if a else True)
            return real_shutdown(self, wait=False)

        fake_brain = mock.Mock()
        fake_brain.think.return_value = _think("Caught up, boss.")

        with app.test_request_context(), \
             mock.patch.object(concurrent.futures.ThreadPoolExecutor,
                               "shutdown", spy_shutdown), \
             mock.patch("server.friday_gmail", None), \
             mock.patch("server.news_anchor", None), \
             mock.patch("server.relationships", None), \
             mock.patch("server.friday_calendar", None), \
             mock.patch("server.friday_brain", fake_brain), \
             mock.patch("server.get_tasks", return_value=[]):
            prompt = "what did i miss"
            server._cmd_catchup(prompt, prompt.lower())

        assert captured.get("wait") is False


class TestOrdinaryOperation:
    """The fix must not change the common, nothing-hangs case."""

    def test_all_three_sources_complete_normally(self, app):
        fake_gmail = mock.Mock()
        fake_gmail.get_unread.return_value = [{"subject": "Hi"}]
        fake_news = mock.Mock()
        fake_news.morning_brief.return_value = "News."
        fake_rel = mock.Mock()
        fake_rel.who_needs_attention.return_value = ["Jane"]
        fake_brain = mock.Mock()
        fake_brain.think.return_value = _think("Caught up, boss.")

        with app.test_request_context(), \
             mock.patch("server.friday_gmail", fake_gmail), \
             mock.patch("server.news_anchor", fake_news), \
             mock.patch("server.relationships", fake_rel), \
             mock.patch("server.friday_calendar", None), \
             mock.patch("server.friday_brain", fake_brain), \
             mock.patch("server.get_tasks", return_value=[{"done": False}]):
            prompt = "what did i miss"
            result = server._cmd_catchup(prompt, prompt.lower())

        assert result is not None
        assert result.get_json()["response"] == "Caught up, boss."

    def test_a_non_triggering_prompt_is_declined(self, app):
        with app.test_request_context():
            assert server._cmd_catchup("what's the weather", "what's the weather") is None


class TestPartialTimeoutStillProducesABrief:
    """as_completed's own TimeoutError used to propagate straight out of
    _cmd_catchup, discarding results from every source that DID answer
    in time. A slow news fetch has nothing to do with whether the boss
    can be told about his email and tasks."""

    def test_data_gathered_before_the_timeout_is_not_discarded(self, app):
        release = threading.Event()

        def hangs(*a, **k):
            release.wait(timeout=5)
            return "too late"

        fake_gmail = mock.Mock()
        fake_gmail.get_unread.return_value = [{"subject": "Real email"}]
        fake_news = mock.Mock()
        fake_news.morning_brief.side_effect = hangs
        fake_brain = mock.Mock()
        fake_brain.think.return_value = _think("Caught up, boss.")

        with app.test_request_context(), \
             mock.patch("server.friday_gmail", fake_gmail), \
             mock.patch("server.news_anchor", fake_news), \
             mock.patch("server.relationships", None), \
             mock.patch("server.friday_calendar", None), \
             mock.patch("server.friday_brain", fake_brain), \
             mock.patch("server.get_tasks", return_value=[]):
            prompt = "what did i miss"
            result = server._cmd_catchup(prompt, prompt.lower())

        release.set()

        assert result is not None
        sent = fake_brain.think.call_args[0][0]
        assert "Real email" in sent
