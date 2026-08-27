"""tests/test_oauth_env_whitespace.py — OAuth env vars must tolerate the
whitespace a hosting dashboard's paste field picks up.

Confirmed live: /friday/calendar/auth returned only
{"error": "Something went wrong, boss."} because
GOOGLE_CALENDAR_REDIRECT_URI carried a trailing newline. That value goes
straight into a Location header via redirect(), and Werkzeug rejects
newlines outright as header-injection protection:

    ValueError: Header values must not contain newline characters.

The generic handler swallowed it, so the real cause was visible only in
the logs -- the same "opaque failure hides a trivial cause" shape as the
SMTP timeouts earlier in this branch. Stripping at read time makes the
paste error a non-event.
"""
import importlib

import pytest


@pytest.fixture(autouse=True)
def _restore_modules():
    """These tests reload the service modules to re-read env vars, which
    leaves their module-level config holding test values. monkeypatch
    restores the environment but not already-reloaded globals, so without
    this the suite is quietly order-dependent -- the same module-state
    leak conftest.py's dispatcher fixture exists to prevent.

    Deliberately doesn't request monkeypatch: as a plain autouse fixture
    it tears down *after* monkeypatch has restored the environment, so
    the final reload picks up the real values rather than the test ones.
    """
    yield
    for name in (
        "services.friday_calendar",
        "services.friday_gmail",
        "services.friday_spotify",
    ):
        module = __import__(name, fromlist=["_"])
        importlib.reload(module)


class TestRedirectUriSurvivesAPastedNewline:
    """The URI is the one that actually detonates -- it reaches a header."""

    def test_calendar_auth_redirects_instead_of_500ing(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_ID", "client-id\n")
        monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_SECRET", "secret\n")
        monkeypatch.setenv(
            "GOOGLE_CALENDAR_REDIRECT_URI",
            "  https://example.com/friday/calendar/callback\n",
        )
        import services.friday_calendar as cal
        importlib.reload(cal)

        assert cal.REDIRECT_URI == "https://example.com/friday/calendar/callback"

        url = cal.FridayCalendar().auth_url()
        assert "\n" not in url and "\r" not in url
        # Werkzeug's own header validation is the real judge here, not a
        # hand-rolled newline check -- this is what actually blew up.
        from werkzeug.utils import redirect
        resp = redirect(url)
        assert resp.status_code == 302

    def test_gmail_send_auth_url_survives_the_same_paste(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_GMAIL_CLIENT_ID", "client-id\n")
        monkeypatch.setenv("GOOGLE_GMAIL_CLIENT_SECRET", "secret\n")
        monkeypatch.setenv(
            "GOOGLE_GMAIL_REDIRECT_URI",
            "https://example.com/friday/gmail/callback\n",
        )
        import services.friday_gmail as gm
        importlib.reload(gm)

        url = gm.FridayGmail().send_auth_url()
        assert "\n" not in url and "\r" not in url
        from werkzeug.utils import redirect
        assert redirect(url).status_code == 302

    def test_spotify_auth_url_survives_the_same_paste(self, monkeypatch):
        monkeypatch.setenv("SPOTIFY_CLIENT_ID", "client-id\n")
        monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "secret\n")
        monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "https://example.com/cb\n")
        import services.friday_spotify as sp
        importlib.reload(sp)

        assert sp.REDIRECT_URI == "https://example.com/cb"


class TestConfiguredIsNotFooledByWhitespaceOnlyValues:
    """A var set to just a newline is not configured -- without the
    strip it reads as truthy and the service claims to be set up."""

    def test_a_whitespace_only_value_is_treated_as_unset(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_ID", "client-id")
        monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_SECRET", "secret")
        monkeypatch.setenv("GOOGLE_CALENDAR_REDIRECT_URI", "   \n")
        import services.friday_calendar as cal
        importlib.reload(cal)

        assert cal.FridayCalendar().is_configured() is False
