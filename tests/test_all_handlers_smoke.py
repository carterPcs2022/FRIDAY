"""tests/test_all_handlers_smoke.py — every dispatch handler claims its
own trigger phrase.

Why this file exists: 351 unit tests passed while a string of real bugs
shipped, and every one was the same shape -- a request that should have
reached a handler fell through the whole dispatch chain to the plain
conversational model, which then improvised. "Put on my calendar ..."
was answered by Spotify. "Can you read my Gmail" was answered "I'm not
able to access your Gmail account" while IMAP was working fine. "remind
me to take my pills" set a reminder and never recorded the medication.

Auditing coverage afterwards showed why none of it was caught: only 12
of 56 dispatch handlers were ever actually invoked by a test.

So this asserts that each handler actually claims a real phrase from its
own trigger list, rather than declining it and letting the request fall
through to the model.

It pairs with tests/test_trigger_shadowing.py, and the split is
deliberate: handlers are called *directly* here, which proves a
capability isn't dead but says nothing about dispatch order. The
shadowing file covers the other half -- that no vaguer trigger earlier in
the chain steals the phrase first, which is what actually broke the
calendar and medication paths. Neither file alone would have caught both
bugs; both together would have caught either.

Every phrase below is taken from the handler's actual trigger list or
inline condition, not invented. That distinction matters: the first
draft of this file used plausible-sounding phrasings and produced five
failures that were all the test's fault, which is its own kind of noise.
"""
from unittest import mock

import pytest

import server


def _brain():
    """friday_brain stand-in. think() must return a real dict -- handlers
    subscript it, and several json.loads the result -- so this returns
    one object carrying every key any handler looks for."""
    b = mock.Mock()
    b.think.return_value = {
        "response": '{"task": "x", "minutes": 30, "title": "x", "to": "a@b.com", '
                    '"subject": "s", "body": "b", "start": "2026-09-01", '
                    '"end": "2026-09-01", "name": "x", "dose": "1", "time": "8am", '
                    '"content": "c", "text": "t", "translation": "t"}',
        "model": "test", "provider": "test", "ms": 1, "tier": "fast",
    }
    b.classify.return_value = "fast"
    return b


# (handler, phrase) -- every phrase verified against the handler's own
# trigger list or inline condition in server.py.
CASES = [
    # Safety / mode
    ("_cmd_safe_checkin",      "i'm safe"),
    ("_cmd_combat_mode",       "combat mode"),
    ("_cmd_normal_mode",       "normal mode"),
    # Knowledge / reasoning
    ("_cmd_news",              "give me the news"),
    ("_cmd_translate",         "translate hello to spanish"),
    ("_cmd_remember_this",     "remember this: the garage code is 4021"),
    ("_cmd_catchup",           "what did i miss"),
    ("_cmd_probability",       "what are the odds"),
    ("_cmd_priority",          "what should i focus on"),
    ("_cmd_focus",             "focus mode"),
    ("_cmd_code_review",       "review this code: print(1)"),
    # People / comms
    ("_cmd_people_brief",      "people brief on jane"),
    ("_cmd_caller_id",         "incoming call from jane"),
    ("_cmd_call_initiate",     "call jane"),
    ("_cmd_sms_send",          "text me the address"),
    # Email
    ("_cmd_email_draft",       "draft a reply to jane"),
    ("_cmd_email_send",        "send it"),
    ("_cmd_email_triage",      "triage my inbox"),
    ("_cmd_email_summary",     "check my email"),
    # Notes / tasks / goals / habits
    ("_cmd_note",              "note that the wifi is slow"),
    ("_cmd_task_show",         "what's on my list"),
    ("_cmd_task_add",          "add to my list buy milk"),
    ("_cmd_goal_report",       "what are my goals"),
    ("_cmd_goal_add",          "add goal run a marathon"),
    ("_cmd_goal_progress",     "worked on the marathon training"),
    ("_cmd_habit_log",         "logged my workout"),
    ("_cmd_journal",           "log today: it was long"),
    # Health
    ("_cmd_med_schedule",      "my medicine schedule"),
    ("_cmd_med_add",           "remind me to take my vitamins at 8am"),
    ("_cmd_med_taken",         "i took my vitamins"),
    ("_cmd_med_skip",          "skip my vitamins"),
    # Time / place
    ("_cmd_reminder",          "remind me in 30 minutes to call back"),
    ("_cmd_calendar_add",      "put on my calendar dentist on September 1st"),
    ("_cmd_travel",            "traveling to Tokyo"),
    # Ops / intel
    ("_cmd_weather",           "what's the weather"),
    ("_cmd_recon",             "run recon on acme corp"),
    # Media / home
    ("_cmd_spotify_play",      "play some AC/DC"),
    ("_cmd_spotify_stop",      "stop playing"),
    ("_cmd_ha_status",         "what's on my home assistant"),
    ("_cmd_ha_toggle",         "turn on the tv"),
]

# Handlers whose signature is (prompt) only, not (prompt, p_lower).
ONE_ARG = {
    "_cmd_lockdown_locked", "_cmd_lockdown_trigger", "_cmd_mayday",
    "_cmd_safe_checkin", "_cmd_security_screen", "_cmd_learn_voice_mode",
    "_cmd_dark_mode", "_cmd_capabilities",
}


def _service_names():
    """Every optional integration core/app_state.py sets to None when its
    import fails -- i.e. the full set of service singletons the handlers
    reach for."""
    import re
    from pathlib import Path
    import core.app_state as st

    src = Path(st.__file__).read_text()
    return set(re.findall(r"^\s*(\w+)\s*=\s*None$", src, re.M))


@pytest.fixture
def all_services(monkeypatch):
    """Replace *every* service global with a Mock -- not just the ones
    that happen to be None here.

    Mocking only the None ones was actively dangerous: any integration
    that imported successfully stayed real and got genuinely exercised.
    Caught exactly that -- "lockdown now" ran the real suit_lockdown and
    persisted a locked state to memory/, so the next boot came up
    LOCKED. A smoke test must not be able to do that.

    It also removes the false-negative side: a handler returning None now
    means it genuinely declined the phrase, not that an optional service
    was unconfigured in this environment."""
    for name in _service_names():
        monkeypatch.setattr(server, name, mock.Mock(), raising=False)

    monkeypatch.setattr(server, "friday_brain", _brain(), raising=False)
    # Pending-reply state otherwise leaks between parametrized cases and
    # lets one handler claim another's phrase.
    monkeypatch.setattr(server, "_pending_calendar_add", {}, raising=False)
    monkeypatch.setattr(server, "_pending_compose_send", {}, raising=False)


@pytest.mark.parametrize("handler,prompt", CASES, ids=[c[0] for c in CASES])
def test_handler_claims_its_own_phrasing(app, all_services, handler, prompt):
    """Returning None means "not mine" -- the request continues down the
    chain and, if nothing else claims it, reaches the conversational
    model. That is exactly how FRIDAY ended up denying she could read
    Gmail, and how Spotify ended up answering a calendar request.

    Scope, stated plainly: this proves the phrase *reaches* the handler,
    not that the handler works end to end. Raising counts as claiming --
    with all 47 services mocked, a handler that enters its body and then
    trips over a Mock where it wanted a dict has still proved the only
    thing under test here. Asserting more would mean hand-building
    realistic return values for 47 services, which is what the
    per-feature test files already do properly for the paths that
    matter. The failure this catches is the silent one: a clean None,
    and an improvised answer in production."""
    fn = getattr(server, handler)
    args = (prompt,) if handler in ONE_ARG else (prompt, prompt.lower())

    with app.test_request_context():
        try:
            result = fn(*args)
        except Exception:
            return  # entered the handler -- the trigger matched

    assert result is not None, (
        f"{handler} did not claim {prompt!r} -- it falls through to the "
        f"conversational model, which will improvise an answer"
    )


def test_every_dispatch_handler_is_covered_or_explicitly_exempt():
    """Stops this file quietly rotting: a handler added to the dispatch
    chain later has to be given a case here or listed as exempt, rather
    than silently joining the 44 that had no coverage at all."""
    import re
    from pathlib import Path

    src = Path(server.__file__).read_text()
    order = []
    for m in re.finditer(r"result = (_cmd_\w+)\(prompt", src):
        if m.group(1) not in order:
            order.append(m.group(1))

    covered = {h for h, _ in CASES}
    # Exempt: these need real device/network state or a live security
    # posture to reach, and a mock-only smoke test would assert nothing
    # meaningful about them.
    exempt = {
        "_cmd_lockdown_locked",    # only fires while already locked down
        "_cmd_lockdown_trigger",   # genuinely destructive: locks the suit and
                                   # persists it, so the next boot comes up LOCKED.
                                   # Covered by tests/test_security.py instead.
        "_cmd_mayday",             # emergency broadcast, has its own tests
        "_cmd_safety_near_miss",   # covered by tests/test_safety_near_miss.py
        "_cmd_security_screen",    # runs the real screening pipeline
        "_cmd_learn_voice_mode",   # depends on enrolled voice state
        "_cmd_dark_mode",
        "_cmd_capabilities",       # CAPABILITY_MAP has its own registry test
        "_cmd_homekit",
        "_cmd_jarvis_proxy",       # proxies to a separate deploy
        "_cmd_self_repair",        # covered by tests/test_self_repair_cannot_run.py
        "_cmd_email_compose_send", # covered by tests/test_email_compose_send.py
        "_cmd_file_recall",
        "_cmd_create_file",
        "_cmd_vision",
        "_cmd_spotify_play_playlist",
        "_cmd_diagnostics",        # reports real host/process state
        "_cmd_cross_check",        # runs the real cross-check pipeline
        "_cmd_mac_app",            # needs the Mac bridge on the other end
    }
    missing = [h for h in order if h not in covered and h not in exempt]
    assert not missing, (
        "dispatch handlers with no smoke coverage and not exempt:\n  "
        + "\n  ".join(missing)
    )
