"""tests/conftest.py — shared fixtures for FRIDAY's test suite.

Tests run against the real server.py app (imported once per test
session, matching how it actually boots) rather than a slimmed-down test
app — the things worth testing here (route registration, the auth gate,
the directory-creation ordering bug) are properties of the real
import-time wiring, and a synthetic stand-in app wouldn't exercise any
of them.

Runs against the unconfigured state -- but *enforces* it rather than
assuming it. Every service here degrades to "unconfigured" cleanly when
its credentials are absent (see core/config_validator.py), and testing
against that state exercises the code path a fresh clone hits without
needing real credentials in CI.

The enforcement matters, and was added after this bit properly:
core/self_repair.py runs this suite on the live deploy to diagnose
FRIDAY's own bugs, and the deploy *does* have real credentials set. With
FRIDAY_ACCESS_TOKEN present, access_auth's gate returned 401 before any
/command test reached its handler, so tests that pass everywhere else
failed there -- and FRIDAY correctly but uselessly reported "found a
failing test" forever. With real-looking API keys present, other tests
tried real network calls and hung.

A suite whose result depends on the environment it runs in can't be used
to diagnose anything. Clearing these before server.py is imported makes
a local run, a CI run and a self-repair run on Render all the same run.
Tests that need a credential set still set it explicitly (monkeypatch +
importlib.reload), which is unaffected.
"""
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)  # server.py uses cwd-relative paths (Path("memory/..."))

# Cleared before server.py is imported below -- see the module docstring.
_ENV_TO_CLEAR = [
    "FRIDAY_ACCESS_TOKEN",
    "EMAIL_ADDRESS", "EMAIL_PASSWORD",
    "GOOGLE_GMAIL_CLIENT_ID", "GOOGLE_GMAIL_CLIENT_SECRET", "GOOGLE_GMAIL_REDIRECT_URI",
    "GOOGLE_CALENDAR_CLIENT_ID", "GOOGLE_CALENDAR_CLIENT_SECRET",
    "GOOGLE_CALENDAR_REDIRECT_URI",
    "SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "SPOTIFY_REDIRECT_URI",
    "ANTHROPIC_API_KEY", "GROQ_API_KEY", "ELEVENLABS_API_KEY",
    "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE",
    "TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN",
    "HA_URL", "HA_TOKEN",
    "MAC_BRIDGE_URL", "MAC_BRIDGE_TOKEN",
    "JARVIS_URL", "JARVIS_API_TOKEN",
    "PUSHOVER_USER_KEY", "PUSHOVER_APP_TOKEN", "PUSHCUT_API_KEY",
    "SERPER_API_KEY", "TAVILY_API_KEY", "SERPAPI_KEY",
    "FRIDAY_OFFLINE_MODEL_URL",
]
for _name in _ENV_TO_CLEAR:
    os.environ.pop(_name, None)


@pytest.fixture(scope="session")
def app():
    """Imports server.py exactly once for the whole test session (Python
    caches the import either way; session scope just makes that
    explicit). server.py starts several daemon background threads at
    import time (JARVIS monitor, config check, morning brief,
    autonomous agent) — harmless here (all try/except-wrapped, all
    daemon=True, network calls time out against nothing listening) but
    means the process doesn't exit purely idle; pytest exiting still
    kills them since they're daemon threads.
    """
    import server
    return server.app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def _reset_pending_followup_state(app):
    """server.py's _pending_compose_send and _pending_calendar_add are
    deliberately module-level, real state (see _cmd_email_compose_send's
    and _cmd_calendar_add's docstrings) -- exactly the kind of thing
    that leaks between tests in the same process if one test leaves it
    non-empty (an incomplete "send an email to..."/"schedule a
    meeting..." that never got a valid follow-up) and a later, unrelated
    test's prompt then gets misread as answering it. Reset before and
    after every test so each one starts and ends clean regardless of
    what ran before or after it."""
    import server
    server._pending_compose_send = {}
    server._pending_calendar_add = {}
    yield
    server._pending_compose_send = {}
    server._pending_calendar_add = {}


@pytest.fixture(autouse=True)
def _isolate_action_ledger(tmp_path, monkeypatch):
    """Point the ledger at a temp file for every test.

    Without this the suite writes real rows into
    memory/friday_action_ledger.json -- 86 of them on the first run after
    the ledger was wired in, all invented test prompts. The file is
    gitignored so none of it would have shipped, but it is the same shape
    as the smoke test that once ran the real suit_lockdown and left the
    next boot LOCKED: a test suite must not be able to write the state
    the application reads back.

    It also keeps the tests honest about each other. A shared ledger
    accumulating across tests would let one test's entries satisfy
    another's assertions about counts or recency."""
    from core import action_ledger
    monkeypatch.setattr(action_ledger, "LEDGER_FILE",
                        tmp_path / "action_ledger.json")
    # Belt and braces: even with the path redirected, a configured Turso
    # would have the suite writing rows to the real database.
    monkeypatch.setattr(action_ledger, "_turso", lambda: None)


def service_names():
    """Every optional integration core/app_state.py sets to None when its
    import fails -- i.e. the full set of service singletons the handlers
    reach for. Read from the source so it can't drift from the real list."""
    import re
    from pathlib import Path
    import core.app_state as app_state
    return set(re.findall(r"^\s*(\w+)\s*=\s*None$",
                          Path(app_state.__file__).read_text(), re.M))


@pytest.fixture
def all_services(monkeypatch):
    """Every service mocked, and the always-on handlers neutralised so a
    prompt actually reaches the chain.

    Mocking the services is the easy half. The half that keeps catching
    people -- three times in one session -- is that a bare Mock returns a
    truthy Mock, so the handlers that run on every request claim
    everything before the chain gets anywhere:

        _cmd_lockdown_locked    suit_lockdown.is_locked() reads as locked
        _cmd_security_screen    screen_request()["blocked"] reads as blocked

    Both sit at the top of PRE_SPLIT, so either one swallows the prompt
    and every assertion below becomes vacuous while still passing. That
    is how a deliberately broken tool-router catalog entry sailed through
    two separate attempts at a guard.

    Three test files each worked this out independently and fixed it
    three different ways -- mocking is_locked, mocking screen_request,
    setting SECURITY_OK False. All correct; none written down. This is
    the one place it lives now.
    """
    from unittest import mock
    import server

    for name in service_names():
        monkeypatch.setattr(server, name, mock.Mock(), raising=False)

    # SECURITY_OK is the handler's own condition, so switching it off is
    # more honest than teaching a Mock to answer "not blocked".
    monkeypatch.setattr(server, "SECURITY_OK", False, raising=False)
    monkeypatch.setattr(server, "VOICE_OK", False, raising=False)
    server.suit_lockdown.is_locked.return_value = False

    # Pending-reply state is real module-level state and leaks between
    # tests in the same process -- an unfinished "schedule a meeting..."
    # makes the next test's prompt look like the answer to it.
    monkeypatch.setattr(server, "_pending_calendar_add", {}, raising=False)
    monkeypatch.setattr(server, "_pending_compose_send", {}, raising=False)
    return server


@pytest.fixture
def extracting_brain(monkeypatch):
    """A brain whose think() returns one object carrying every key any
    handler looks for. Several json.loads the result, so it has to be
    real parseable JSON rather than a Mock."""
    import json
    from unittest import mock
    import server

    brain = mock.Mock()
    brain.think.return_value = {
        "response": json.dumps({
            "task": "x", "minutes": 30, "title": "x", "to": "a@b.com",
            "subject": "s", "body": "b", "start": "2026-09-01",
            "end": "2026-09-01", "name": "x", "dose": "1", "time": "8am",
            "content": "c", "text": "t", "translation": "t",
        }),
        "model": "test", "provider": "test", "ms": 1, "tier": "fast",
    }
    brain.classify.return_value = "fast"
    monkeypatch.setattr(server, "friday_brain", brain, raising=False)
    return brain
