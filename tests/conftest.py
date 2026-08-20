"""tests/conftest.py — shared fixtures for FRIDAY's test suite.

Tests run against the real server.py app (imported once per test
session, matching how it actually boots) rather than a slimmed-down test
app — the things worth testing here (route registration, the auth gate,
the directory-creation ordering bug) are properties of the real
import-time wiring, and a synthetic stand-in app wouldn't exercise any
of them.

Deliberately does NOT set fake API keys before import. Every service in
this codebase already degrades to "unconfigured" cleanly when its
credentials are absent (see core/config_validator.py's whole reason for
existing) — testing against that natural unconfigured state exercises
the exact code path a fresh clone or a partially-configured deploy hits,
without needing real credentials in CI or on a contributor's machine.
"""
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)  # server.py uses cwd-relative paths (Path("memory/..."))


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
