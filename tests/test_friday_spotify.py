"""tests/test_friday_spotify.py — services/friday_spotify.py.

Two things this pins down:

1. Token persistence. Same bug and same fix as
   tests/test_calendar_token_persistence.py: render.yaml mounts no disk,
   so memory/friday_spotify_token.json is lost on every redeploy and
   every free-tier idle spin-down. Unlike Calendar and Gmail, Spotify's
   token was never mirrored to Turso -- confirmed live when a
   freshly-tested /friday/spotify/auth link needed re-authorizing far
   more often than the token's own ~1-hour access-token lifetime would
   explain.

2. Three call-shape bugs in play(): it grabbed devices[0] instead of
   preferring whatever Spotify itself marks as the active device, the
   search call parsed a response body without checking its status code
   first, and a token that Spotify rejects mid-call (revoked, or expired
   earlier than our own clock expected) had no path back to a working
   token within the same request.
"""
import json
import time
from unittest import mock

import pytest

import services.friday_spotify as spotify_mod
from services.friday_spotify import friday_spotify


def _resp(status_code=200, json_data=None, text=""):
    return mock.Mock(status_code=status_code, json=lambda: json_data or {}, text=text)


@pytest.fixture
def configured(monkeypatch, tmp_path):
    monkeypatch.setattr(spotify_mod, "CLIENT_ID", "client-id")
    monkeypatch.setattr(spotify_mod, "CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(spotify_mod, "REDIRECT_URI", "https://example.com/friday/spotify/callback")
    monkeypatch.setattr(spotify_mod, "SPOTIFY_TOKEN_FILE", tmp_path / "spotify_token.json")
    monkeypatch.setattr(spotify_mod.turso, "is_configured", lambda: False)
    return tmp_path


class TestTokenSurvivesARedeploy:

    def test_the_token_is_mirrored_to_turso_on_save(self, configured, monkeypatch):
        written = {}
        monkeypatch.setattr(spotify_mod.turso, "is_configured", lambda: True)
        monkeypatch.setattr(spotify_mod.turso, "ensure_kv_table", lambda t: None)
        monkeypatch.setattr(
            spotify_mod.turso, "kv_set",
            lambda table, key, data: written.update({"table": table, "key": key, "data": data}),
        )

        friday_spotify._save_token({
            "access_token": "a", "refresh_token": "r", "expires_at": 1,
        })

        assert written["data"]["refresh_token"] == "r"

    def test_the_token_is_read_back_from_turso_when_local_disk_is_empty(
        self, configured, monkeypatch
    ):
        """The actual redeploy scenario: fresh container, no local file,
        but the boss authorized before the deploy."""
        monkeypatch.setattr(spotify_mod, "SPOTIFY_TOKEN_FILE", configured / "gone.json")
        monkeypatch.setattr(spotify_mod.turso, "is_configured", lambda: True)
        monkeypatch.setattr(spotify_mod.turso, "ensure_kv_table", lambda t: None)
        monkeypatch.setattr(
            spotify_mod.turso, "kv_get",
            lambda table, key: {
                "access_token": "survived", "refresh_token": "survived-refresh",
                "expires_at": time.time() + 3600,
            },
        )

        assert friday_spotify._get_token() == "survived"

    def test_a_turso_outage_falls_back_to_local_disk_rather_than_breaking(
        self, configured, monkeypatch
    ):
        """Turso being down must not take Spotify control down with it
        when the local copy is right there."""
        token_file = configured / "spotify_token.json"
        token_file.write_text(json.dumps({
            "access_token": "local-copy", "refresh_token": "local-refresh",
            "expires_at": time.time() + 3600,
        }))

        monkeypatch.setattr(spotify_mod.turso, "is_configured", lambda: True)
        monkeypatch.setattr(spotify_mod.turso, "ensure_kv_table", lambda t: None)
        monkeypatch.setattr(
            spotify_mod.turso, "kv_get",
            mock.Mock(side_effect=RuntimeError("turso unreachable")),
        )

        assert friday_spotify._get_token() == "local-copy"

    def test_a_refreshed_access_token_is_persisted_to_both_stores(
        self, configured, monkeypatch
    ):
        """The refresh path reads the stored token, updates it, and saves
        it back -- if that round trip dropped the Turso mirror, the
        connection would still die on the next redeploy despite the
        mirror existing."""
        token_file = configured / "spotify_token.json"
        token_file.write_text(json.dumps({
            "access_token": "stale", "refresh_token": "refresh-me",
            "expires_at": time.time() - 10,   # expired
        }))

        written = {}
        monkeypatch.setattr(spotify_mod.turso, "is_configured", lambda: True)
        monkeypatch.setattr(spotify_mod.turso, "ensure_kv_table", lambda t: None)
        monkeypatch.setattr(spotify_mod.turso, "kv_get", lambda table, key: None)
        monkeypatch.setattr(
            spotify_mod.turso, "kv_set",
            lambda table, key, data: written.update(data),
        )

        fake = _resp(200, {"access_token": "fresh", "expires_in": 3600})
        with mock.patch("httpx.post", lambda url, **kw: fake):
            token = friday_spotify._get_token()

        assert token == "fresh"
        assert written["access_token"] == "fresh"
        assert written["refresh_token"] == "refresh-me"
        assert json.loads(token_file.read_text())["access_token"] == "fresh"


class TestPlayPrefersTheActiveDevice:

    def test_the_device_spotify_marks_active_is_used_over_the_first_in_the_list(
        self, configured
    ):
        """The exact gap: two devices registered (an idle laptop plus
        the phone actually in hand), phone listed second. Blindly taking
        devices[0] would target the laptop."""
        friday_spotify._save_token({
            "access_token": "tok", "refresh_token": "r", "expires_at": time.time() + 3600,
        })
        devices_resp = _resp(200, {"devices": [
            {"id": "laptop-id", "is_active": False},
            {"id": "phone-id", "is_active": True},
        ]})
        play_resp = _resp(204)

        calls = []

        def fake_request(method, url, **kw):
            calls.append((method, url))
            if "devices" in url:
                return devices_resp
            return play_resp

        with mock.patch("httpx.request", fake_request):
            result = friday_spotify.play()

        assert result == {"playing": True}
        play_call = next(c for c in calls if "device_id=" in c[1])
        assert "device_id=phone-id" in play_call[1]

    def test_falls_back_to_the_first_device_when_none_is_marked_active(self, configured):
        """Must not regress the ordinary single-device case, where
        is_active can legitimately be false or absent on everything."""
        friday_spotify._save_token({
            "access_token": "tok", "refresh_token": "r", "expires_at": time.time() + 3600,
        })
        devices_resp = _resp(200, {"devices": [{"id": "only-device", "is_active": False}]})
        play_resp = _resp(204)

        calls = []

        def fake_request(method, url, **kw):
            calls.append((method, url))
            return devices_resp if "devices" in url else play_resp

        with mock.patch("httpx.request", fake_request):
            result = friday_spotify.play()

        assert result == {"playing": True}
        play_call = next(c for c in calls if "device_id=" in c[1])
        assert "device_id=only-device" in play_call[1]


class TestSearchChecksStatusBeforeParsing:

    def test_a_failed_search_reports_the_status_instead_of_raising(self, configured):
        """Previously called r.json() unconditionally -- a 429 rate
        limit or a malformed error body surfaced as a generic caught
        exception string instead of a clear "search failed"."""
        friday_spotify._save_token({
            "access_token": "tok", "refresh_token": "r", "expires_at": time.time() + 3600,
        })
        devices_resp = _resp(200, {"devices": [{"id": "d1", "is_active": True}]})
        search_resp = _resp(429, text="rate limited")

        def fake_request(method, url, **kw):
            return devices_resp if "devices" in url else search_resp

        with mock.patch("httpx.request", fake_request):
            result = friday_spotify.play("some song")

        assert result == {"error": "Search failed: 429"}


class TestReauthOn401MidCall:

    def test_a_401_triggers_one_refresh_and_retry(self, configured, monkeypatch):
        """A token Spotify rejects mid-call -- revoked, or expired
        earlier than our own clock expected -- must recover within the
        same request rather than surfacing as an opaque failure."""
        friday_spotify._save_token({
            "access_token": "stale-tok", "refresh_token": "refresh-me",
            "expires_at": time.time() + 3600,   # not expired by our own clock
        })

        refresh_resp = _resp(200, {"access_token": "fresh-tok", "expires_in": 3600})
        devices_resp = _resp(200, {"devices": [{"id": "d1", "is_active": True}]})
        play_unauthed = _resp(401)
        play_ok = _resp(204)

        seen_tokens = []

        def fake_request(method, url, headers=None, **kw):
            token = (headers or {}).get("Authorization", "")
            if "devices" in url:
                seen_tokens.append(("devices", token))
                return devices_resp
            seen_tokens.append(("play", token))
            return play_unauthed if "stale-tok" in token else play_ok

        with mock.patch("httpx.request", fake_request), \
             mock.patch("httpx.post", lambda url, **kw: refresh_resp):
            result = friday_spotify.play()

        assert result == {"playing": True}
        play_attempts = [t for (kind, t) in seen_tokens if kind == "play"]
        assert "Bearer stale-tok" in play_attempts[0]
        assert "Bearer fresh-tok" in play_attempts[-1]

    def test_a_persistent_401_does_not_loop_forever(self, configured, monkeypatch):
        """A refresh token Spotify has also revoked must fail cleanly
        after exactly one retry, not retry indefinitely."""
        friday_spotify._save_token({
            "access_token": "stale-tok", "refresh_token": "dead-refresh",
            "expires_at": time.time() + 3600,
        })

        dead_refresh_resp = _resp(400)
        devices_resp = _resp(200, {"devices": [{"id": "d1", "is_active": True}]})
        play_unauthed = _resp(401)

        call_count = {"play": 0}

        def fake_request(method, url, headers=None, **kw):
            if "devices" in url:
                return devices_resp
            call_count["play"] += 1
            return play_unauthed

        with mock.patch("httpx.request", fake_request), \
             mock.patch("httpx.post", lambda url, **kw: dead_refresh_resp):
            result = friday_spotify.play()

        assert result == {"playing": False}
        # One initial attempt, one retry -- refresh failed, so no third try.
        assert call_count["play"] == 1
