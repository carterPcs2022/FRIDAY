"""tests/test_cors.py — cross-origin access, allow-listed and
credential-free.

FRIDAY's HUD is same-origin, so nothing ever needed CORS; a page on
another origin is blocked by the browser before the request reaches her.
Opening that up needs care on this particular server, because she reads
the boss's email, calendar, notes and location.

The three properties that keep it safe are all tested here: no wildcard,
no credentials, and an explicit allow-list. The credential one matters
most -- without Access-Control-Allow-Credentials a browser will not
attach the friday_auth cookie to a cross-origin request, which closes
the shape where a page the boss happens to be visiting rides his
logged-in session.
"""
import importlib
import os

import pytest


@pytest.fixture
def cors_allowing(monkeypatch):
    """Reload the module with an allow-list, since it reads the env at
    import time, and point server at the reloaded copy."""
    def _setup(origins):
        monkeypatch.setenv("FRIDAY_CORS_ORIGINS", origins)
        import core.cors as cors
        importlib.reload(cors)
        import server
        monkeypatch.setattr(server, "_cors", cors)
        return cors
    yield _setup
    import core.cors as cors
    monkeypatch.delenv("FRIDAY_CORS_ORIGINS", raising=False)
    importlib.reload(cors)


def _ac(resp):
    return {k.lower(): v for k, v in resp.headers if k.lower().startswith("access-control")}


class TestAllowListing:

    def test_an_allowed_origin_gets_headers(self, client, cors_allowing):
        cors_allowing("https://claude.ai")
        r = client.post("/command", json={"prompt": "hi"},
                        headers={"Origin": "https://claude.ai"})
        assert _ac(r)["access-control-allow-origin"] == "https://claude.ai"

    def test_an_unlisted_origin_gets_nothing(self, client, cors_allowing):
        """The browser is what enforces this -- absent headers means it
        refuses to hand the response to the calling page."""
        cors_allowing("https://claude.ai")
        r = client.post("/command", json={"prompt": "hi"},
                        headers={"Origin": "https://evil.example.com"})
        assert _ac(r) == {}

    def test_no_origins_configured_means_no_cross_origin_access(self, client, cors_allowing):
        """The default, and what every deploy did before this existed."""
        cors_allowing("")
        r = client.post("/command", json={"prompt": "hi"},
                        headers={"Origin": "https://claude.ai"})
        assert _ac(r) == {}

    def test_multiple_origins_are_supported(self, client, cors_allowing):
        cors_allowing("https://claude.ai, https://example.com")
        for origin in ("https://claude.ai", "https://example.com"):
            r = client.get("/health", headers={"Origin": origin})
            assert _ac(r)["access-control-allow-origin"] == origin


class TestTheSafetyProperties:

    def test_credentials_are_never_allowed(self, client, cors_allowing):
        """Without this header the browser won't attach the friday_auth
        cookie cross-origin, so a page the boss is visiting can't ride
        his session. Cross-origin callers use the token explicitly."""
        cors_allowing("https://claude.ai")
        r = client.post("/command", json={"prompt": "hi"},
                        headers={"Origin": "https://claude.ai"})
        assert "access-control-allow-credentials" not in _ac(r)

    def test_the_wildcard_is_never_sent(self, client, cors_allowing):
        cors_allowing("https://claude.ai")
        r = client.get("/health", headers={"Origin": "https://claude.ai"})
        assert _ac(r)["access-control-allow-origin"] != "*"

    def test_vary_origin_is_set(self, client, cors_allowing):
        """The same URL answers differently per origin; without Vary a
        shared cache could hand one origin's headers to another."""
        cors_allowing("https://claude.ai")
        r = client.get("/health", headers={"Origin": "https://claude.ai"})
        assert "Origin" in r.headers.get("Vary", "")


class TestPreflight:
    """A preflight carries no credentials by design -- the browser sends
    it before deciding whether it may send the real request. Gating it
    behind auth would 401 it, the browser would never send the actual
    request, and the failure would surface as an opaque CORS error rather
    than an auth one."""

    def test_preflight_succeeds_without_auth(self, client, cors_allowing, monkeypatch):
        cors_allowing("https://claude.ai")
        import core.access_auth as access_auth
        monkeypatch.setattr(access_auth, "ACCESS_TOKEN", "a-real-token")

        r = client.open("/command", method="OPTIONS",
                        headers={"Origin": "https://claude.ai"})

        assert r.status_code == 200, "preflight was blocked by the auth gate"
        assert _ac(r)["access-control-allow-origin"] == "https://claude.ai"

    def test_preflight_advertises_the_authorization_header(self, client, cors_allowing):
        """Cross-origin callers authenticate with a header instead of the
        cookie, so the browser has to be told that header is permitted."""
        cors_allowing("https://claude.ai")
        r = client.open("/command", method="OPTIONS",
                        headers={"Origin": "https://claude.ai"})
        assert "Authorization" in _ac(r)["access-control-allow-headers"]

    def test_a_real_request_still_needs_auth(self, client, cors_allowing, monkeypatch):
        """Exempting preflight must not exempt anything else."""
        cors_allowing("https://claude.ai")
        import core.access_auth as access_auth
        monkeypatch.setattr(access_auth, "ACCESS_TOKEN", "a-real-token")

        r = client.post("/command", json={"prompt": "hi"},
                        headers={"Origin": "https://claude.ai"})
        assert r.status_code == 401, "the auth gate stopped applying to real requests"


class TestSameOriginIsUnaffected:
    def test_a_request_with_no_origin_header_is_untouched(self, client, cors_allowing):
        cors_allowing("https://claude.ai")
        r = client.get("/health")
        assert r.status_code == 200
        assert _ac(r) == {}
