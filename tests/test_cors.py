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


class TestBlockedOriginReadback:
    """The allow-list is useless if you can't find out what to put in it.

    A page that needs allow-listing doesn't have a guessable origin -- a
    sandboxed artifact can arrive as "null" or as a per-page domain --
    and the only place the real value appeared was a log line. Copying a
    string out of Render's log viewer is a round trip, and guessing wrong
    is another. /cors-check makes the value readable from the browser
    that's already signed in.
    """

    def test_rejection_is_recorded_for_readback(self, cors_allowing):
        cors = cors_allowing("https://allowed.example")
        from flask import Response
        cors.apply(Response(), "https://stranger.example")

        blocked = [b["origin"] for b in cors.blocked_origins()]
        assert "https://stranger.example" in blocked

    def test_allowed_origin_is_not_recorded_as_blocked(self, cors_allowing):
        cors = cors_allowing("https://allowed.example")
        from flask import Response
        cors.apply(Response(), "https://allowed.example")

        assert cors.blocked_origins() == []

    def test_null_origin_survives_readback(self, cors_allowing):
        """The literal string "null" is what a sandboxed iframe sends,
        and it's the single most likely value the boss actually needs to
        see -- so it must not be dropped as falsy or normalised away."""
        cors = cors_allowing("https://allowed.example")
        from flask import Response
        cors.apply(Response(), "null")

        assert [b["origin"] for b in cors.blocked_origins()] == ["null"]

    def test_repeat_attempts_count_rather_than_duplicate(self, cors_allowing):
        cors = cors_allowing("https://allowed.example")
        from flask import Response
        for _ in range(3):
            cors.apply(Response(), "https://stranger.example")

        blocked = cors.blocked_origins()
        assert len(blocked) == 1
        assert blocked[0]["count"] == 3

    def test_record_is_bounded(self, cors_allowing):
        """Reachable from the open internet, and the process is
        long-lived -- an unbounded record here is a slow memory leak
        anyone could drive."""
        cors = cors_allowing("https://allowed.example")
        from flask import Response
        for i in range(cors._MAX_BLOCKED + 20):
            cors.apply(Response(), f"https://probe{i}.example")

        assert len(cors.blocked_origins()) <= cors._MAX_BLOCKED

    def test_eviction_keeps_the_origin_still_retrying(self, cors_allowing):
        """The whole point is to surface the page the boss is actively
        trying to connect. A burst of one-off probes arriving afterwards
        must not push it out -- so eviction goes by least-recently-seen,
        not by insertion order."""
        cors = cors_allowing("https://allowed.example")
        from flask import Response
        cors.apply(Response(), "https://artifact.example")

        for i in range(cors._MAX_BLOCKED - 1):
            cors.apply(Response(), f"https://probe{i}.example")
        # The page retries, refreshing its recency.
        cors.apply(Response(), "https://artifact.example")
        # Now a probe arrives that forces an eviction.
        cors.apply(Response(), "https://late-probe.example")

        assert "https://artifact.example" in [b["origin"] for b in cors.blocked_origins()]

    def test_newest_rejection_is_listed_first(self, cors_allowing):
        cors = cors_allowing("https://allowed.example")
        from flask import Response
        cors.apply(Response(), "https://first.example")
        cors.apply(Response(), "https://second.example")

        assert cors.blocked_origins()[0]["origin"] == "https://second.example"


class TestCorsCheckRoute:
    def test_reports_allow_list_and_rejections(self, client, cors_allowing):
        cors = cors_allowing("https://allowed.example")
        client.post("/friday/ask", headers={"Origin": "https://stranger.example"},
                    json={"message": "hi"})

        body = client.get("/cors-check").get_json()
        assert body["allowed_origins"] == ["https://allowed.example"]
        assert body["configured"] is True
        assert "https://stranger.example" in [b["origin"] for b in body["blocked"]]

    def test_reports_unconfigured_rather_than_pretending(self, client):
        """Empty allow-list is the default, and it's the single most
        likely reason a page is failing. It has to be distinguishable
        from "configured, but this origin isn't on it"."""
        body = client.get("/cors-check").get_json()
        assert body["configured"] is False
        assert body["allowed_origins"] == []

    def test_requires_authentication(self, monkeypatch, client):
        """It lists origins that have called her. Behind the same gate as
        everything else, not exempt."""
        import core.access_auth as access_auth
        assert not access_auth.is_exempt("/cors-check")
