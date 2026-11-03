"""tests/test_fact_commands.py — the boss can see and delete what FRIDAY
learned, and a vague "forget ..." can't hijack normal conversation. Also
covers the brain-down alarm."""
import time
from unittest import mock

import pytest

from core import fact_commands as fc


@pytest.fixture
def store(monkeypatch):
    """In-memory stand-in for friday_memory's fact store."""
    from core import friday_memory as fm
    facts = ["User builds JARVIS V5", "User uses UptimeRobot to ping FRIDAY",
             "User likes short replies"]
    monkeypatch.setattr(fm, "get_facts", lambda n=10: list(facts)[-n:])
    monkeypatch.setattr(fm, "delete_fact",
                        lambda f: (facts.remove(f) or True) if f in facts else False)
    monkeypatch.setattr(fc, "_last_listing", [])
    return facts


def test_list_is_numbered_newest_first(store):
    reply = fc.handle("What do you know about me?")
    assert reply.startswith("Here's what I've picked up")
    assert "1. User likes short replies" in reply
    assert "3. User builds JARVIS V5" in reply


def test_list_when_empty(monkeypatch):
    from core import friday_memory as fm
    monkeypatch.setattr(fm, "get_facts", lambda n=10: [])
    assert "haven't picked up anything" in fc.handle("what do you know about me")


def test_forget_by_number_needs_a_list_first(store):
    assert "first" in fc.handle("forget fact 1")
    fc.handle("what do you know about me")
    assert "forgot: User likes short replies" in fc.handle("forget fact 1")
    assert "User likes short replies" not in store


def test_forget_number_out_of_range(store):
    fc.handle("what do you know about me")
    assert "no number 9" in fc.handle("forget fact 9")


def test_forget_by_text_single_clear_match(store):
    reply = fc.handle("forget that I use UptimeRobot")
    assert "forgot: User uses UptimeRobot to ping FRIDAY" in reply
    assert len(store) == 2


def test_forget_by_text_ambiguous_asks_which(store):
    store.append("User builds FRIDAY V2")
    reply = fc.handle("forget that i build things")  # 'build' only matches loosely
    # Either asks which or declines to act -- it must not silently delete.
    assert len(store) == 4


def test_vague_forget_falls_through(store):
    assert fc.handle("forget that meeting happened yesterday") is None
    assert fc.handle("forget it") is None
    assert len(store) == 3


def test_unrelated_message_is_ignored(store):
    assert fc.handle("what's the weather") is None


# ── brain alarm ─────────────────────────────────────────────────────────────
def _agent():
    from core.autonomous_agent import AutonomousAgent
    return AutonomousAgent()


def test_brain_alarm_fires_after_three_failures_once(monkeypatch):
    from core import friday_brain as fb
    monkeypatch.setattr(fb, "ANTHROPIC_KEY", "x")
    monkeypatch.setattr(fb, "_anthropic_fail_streak", 3)
    monkeypatch.setattr(fb, "_last_anthropic_failure", time.time())
    monkeypatch.setattr(fb, "_last_anthropic_error", "NotFoundError")
    ag = _agent()
    with mock.patch.object(ag, "_alert") as alert:
        ag._brain_health_alarm()
        ag._brain_health_alarm()  # cooldown
    assert alert.call_count == 1
    assert "NotFoundError" in alert.call_args.args[0]


def test_brain_alarm_quiet_when_healthy(monkeypatch):
    from core import friday_brain as fb
    monkeypatch.setattr(fb, "ANTHROPIC_KEY", "x")
    monkeypatch.setattr(fb, "_anthropic_fail_streak", 1)
    ag = _agent()
    with mock.patch.object(ag, "_alert") as alert:
        ag._brain_health_alarm()
    alert.assert_not_called()


def test_streak_counts_failures_and_resets_on_success(monkeypatch):
    from core import friday_brain as fb
    import budget_2
    monkeypatch.setattr(fb, "ANTHROPIC_KEY", "x")
    monkeypatch.setattr(fb, "_anthropic_fail_streak", 0)
    monkeypatch.setattr(budget_2, "can_call", lambda: True)
    monkeypatch.setattr(budget_2, "record_call", lambda *a, **k: None)
    boom = mock.MagicMock(side_effect=RuntimeError("nope"))
    ok_resp = mock.MagicMock()
    ok_resp.content = [mock.MagicMock(text="hi")]
    ok_resp.usage.output_tokens = 1
    with mock.patch("anthropic.Anthropic") as A:
        A.return_value.messages.create = boom
        fb.friday_brain._call_anthropic([{"role": "user", "content": "x"}], "s", "m")
        fb.friday_brain._call_anthropic([{"role": "user", "content": "x"}], "s", "m")
        assert fb._anthropic_fail_streak == 2
        A.return_value.messages.create = mock.MagicMock(return_value=ok_resp)
        fb.friday_brain._call_anthropic([{"role": "user", "content": "x"}], "s", "m")
    assert fb._anthropic_fail_streak == 0
