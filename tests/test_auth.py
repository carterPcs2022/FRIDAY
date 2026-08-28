"""tests/test_auth.py — core/access_auth.py's gate logic, plus the
/login open-redirect regression from today's review pass."""
import pytest

from core import access_auth


@pytest.fixture()
def configured_token(monkeypatch):
    """ACCESS_TOKEN is read from the environment once at import time --
    monkeypatching the module attribute directly (rather than the env
    var, which would already be too late) exercises the exact same
    check_token()/has_valid_session() code every real request goes
    through, without needing to reimport the module."""
    monkeypatch.setattr(access_auth, "ACCESS_TOKEN", "test-secret-token")
    return "test-secret-token"


def test_unconfigured_gate_is_open(monkeypatch):
    monkeypatch.setattr(access_auth, "ACCESS_TOKEN", "")
    assert access_auth.is_configured() is False
    assert access_auth.check_token("anything") is False


def test_check_token_correct_and_incorrect(configured_token):
    assert access_auth.check_token(configured_token) is True
    assert access_auth.check_token("wrong-token") is False
    assert access_auth.check_token("") is False


def test_session_cookie_roundtrip(configured_token):
    cookie = access_auth.session_cookie_value()
    assert access_auth.has_valid_session(cookie) is True
    assert access_auth.has_valid_session("forged-cookie-value") is False
    assert access_auth.has_valid_session("") is False


def test_exempt_paths():
    assert access_auth.is_exempt("/health") is True
    assert access_auth.is_exempt("/login") is True
    assert access_auth.is_exempt("/friday/lockdown") is True
    assert access_auth.is_exempt("/friday/tasks") is False
    assert access_auth.is_exempt("/command") is False


class TestLoginOpenRedirect:
    """Regression coverage for the backslash bypass fixed in today's
    review pass: "/\\evil.com" passes a bare `startswith("//")` check
    (only one leading slash) but WHATWG URL parsing treats \\ as / for
    http(s) links, so browsers resolve it identically to "//evil.com"
    right after a successful login."""

    def _is_next_path_safe(self, next_path: str) -> bool:
        # Mirrors the exact guard in server.py's login() route -- kept
        # here as its own testable expression since that logic lives
        # inline in the route rather than a separate function. If
        # server.py's check ever changes, this needs to move with it.
        return next_path.startswith("/") and not next_path.replace("\\", "/").startswith("//")

    @pytest.mark.parametrize("bad_path", [
        "//evil.com",
        "/\\evil.com",
        "/\\/evil.com",
        "\\evil.com",
        "//\\evil.com",
    ])
    def test_bypass_attempts_rejected(self, bad_path):
        assert self._is_next_path_safe(bad_path) is False

    @pytest.mark.parametrize("good_path", ["/hud", "/friday/tasks", "/", "/login?x=1"])
    def test_normal_paths_allowed(self, good_path):
        assert self._is_next_path_safe(good_path) is True

    def test_full_login_flow_rejects_backslash_redirect(self, client, configured_token):
        resp = client.post(
            "/login",
            data={"token": configured_token},
            query_string={"next": "/\\evil.com"},
        )
        assert resp.status_code in (302, 303)
        location = resp.headers.get("Location", "")
        # The fix falls back to /hud rather than honoring the bypass attempt.
        assert location == "/hud", f"open-redirect bypass not blocked, got Location: {location!r}"

    def test_full_login_flow_allows_normal_next(self, client, configured_token):
        resp = client.post(
            "/login",
            data={"token": configured_token},
            query_string={"next": "/friday/tasks"},
        )
        assert resp.headers.get("Location", "") == "/friday/tasks"


class TestUnauthenticatedNavigationGetsTheLoginForm:
    """A signed-out browser used to get {"error":"Unauthorized"} on every
    page except /hud.

    That reads as a broken deploy rather than "you aren't signed in", and
    it leaves no obvious way forward except appending ?token= to the URL
    -- which works, but puts the access token in browser history. The
    gate now shows the login form to anything that navigated to a page,
    while API clients keep the 401 they can handle.
    """

    def test_page_navigation_redirects_to_login(self, client, configured_token):
        res = client.get("/cors-check", headers={"Accept": "text/html"})
        assert res.status_code == 302
        assert res.headers["Location"] == "/login?next=/cors-check"

    def test_hud_still_redirects(self, client, configured_token):
        """The behaviour that already existed, kept."""
        res = client.get("/hud", headers={"Accept": "text/html"})
        assert res.status_code == 302
        assert res.headers["Location"].startswith("/login")

    def test_api_client_still_gets_401(self, client, configured_token):
        """fetch() and URLSession default to Accept: */*. A redirect to
        an HTML login form would be useless to them and would turn a
        clean 401 into a confusing 200-with-HTML."""
        res = client.get("/cors-check", headers={"Accept": "*/*"})
        assert res.status_code == 401
        assert res.get_json()["error"] == "Unauthorized"

    def test_post_is_never_redirected(self, client, configured_token):
        """Redirecting a POST loses the body, so a browser form landing
        on an expired session would silently discard what was typed.
        Method is part of the condition for that reason."""
        res = client.post("/command", headers={"Accept": "text/html"},
                          json={"prompt": "hi"})
        assert res.status_code == 401

    def test_relay_page_handshake_is_unaffected(self, client, configured_token):
        """The exact shape the relay page sends: a cross-origin fetch
        with a bearer token and no Accept override."""
        res = client.post(
            "/friday/ask",
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer test-secret-token",
                     "Origin": "https://relay.example"},
            json={"message": "__relay_handshake__"},
        )
        assert res.status_code != 401

    def test_authenticated_navigation_is_not_redirected(self, client, configured_token):
        res = client.get("/cors-check",
                         headers={"Accept": "text/html"},
                         query_string={"token": configured_token})
        assert res.status_code == 200
