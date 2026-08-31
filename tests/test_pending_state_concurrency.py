"""tests/test_pending_state_concurrency.py — render.yaml now runs gunicorn
with --worker-class gthread --threads 4 instead of the old single-threaded
sync default, specifically so a quick /friday/voice/audio fetch or the
HUD's ~1s /friday/hud/poll loop doesn't queue for tens of seconds behind
a slow /command call (an LLM round trip plus TTS generation) -- the
mechanism behind the live "text appears, voice takes ~30s to speak"
symptom.

That change makes _cmd_calendar_add and _cmd_email_compose_send
reachable concurrently for the first time. Both read module-level pending
state (_pending_calendar_add / _pending_compose_send), do a slow LLM call,
then write it back -- a real TOCTOU race under threads: two overlapping
requests could each read "no pending state," both run the extraction call,
and the second write clobbers the first. Both handlers now hold a lock
across their whole body via a thin wrapper (_cmd_calendar_add ->
_calendar_add_impl, _cmd_email_compose_send -> _email_compose_send_impl).
This proves the wrapper actually serializes concurrent calls, without
needing to simulate the full real body.
"""
import threading
import time

import server


def _assert_serializes(monkeypatch, wrapper_name, impl_attr):
    concurrent = {"count": 0, "max": 0}
    guard = threading.Lock()

    def fake_impl(prompt, p_lower):
        with guard:
            concurrent["count"] += 1
            concurrent["max"] = max(concurrent["max"], concurrent["count"])
        time.sleep(0.05)
        with guard:
            concurrent["count"] -= 1
        return "ok"

    monkeypatch.setattr(server, impl_attr, fake_impl)
    wrapper = getattr(server, wrapper_name)

    threads = [threading.Thread(target=wrapper, args=("p", "p")) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert concurrent["max"] == 1, (
        f"{wrapper_name} let concurrent calls into its critical section -- "
        f"the lock isn't actually serializing them"
    )


class TestCalendarAddIsSerialized:
    def test_concurrent_calls_never_overlap(self, monkeypatch):
        _assert_serializes(monkeypatch, "_cmd_calendar_add", "_calendar_add_impl")


class TestComposeSendIsSerialized:
    def test_concurrent_calls_never_overlap(self, monkeypatch):
        _assert_serializes(monkeypatch, "_cmd_email_compose_send", "_email_compose_send_impl")


class TestLocksAreRealLocks:
    def test_calendar_add_lock_is_a_real_lock(self):
        assert isinstance(server._calendar_add_lock, type(threading.Lock()))

    def test_compose_send_lock_is_a_real_lock(self):
        assert isinstance(server._compose_send_lock, type(threading.Lock()))

    def test_the_two_handlers_do_not_share_one_lock(self):
        """Different pending-state dicts, different locks -- an in-flight
        calendar add must not block an unrelated email compose."""
        assert server._calendar_add_lock is not server._compose_send_lock
