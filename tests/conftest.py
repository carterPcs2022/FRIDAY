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
