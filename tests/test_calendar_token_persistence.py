"""tests/test_calendar_token_persistence.py — the Calendar OAuth token has
to outlive the container.

render.yaml mounts no disk, so memory/ is ephemeral: a token kept only on
local disk is gone on every redeploy and every free-tier idle spin-down,
which would mean re-running the consent flow constantly and would read as
"the calendar integration is broken again". Same fix and same reasoning
as services/friday_gmail.py's send token (see
tests/test_friday_gmail_send.py::TestTokenSurvivesARedeploy) -- this one
was the pre-existing case, predating the Gmail work.
"""
import json
import time
from unittest import mock

import pytest

import services.friday_calendar as cal_mod
from services.friday_calendar import friday_calendar


@pytest.fixture
def configured(monkeypatch, tmp_path):
    monkeypatch.setattr(cal_mod, "CLIENT_ID", "client-id")
    monkeypatch.setattr(cal_mod, "CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(cal_mod, "REDIRECT_URI", "https://example.com/friday/calendar/callback")
    monkeypatch.setattr(cal_mod, "TOKEN_FILE", tmp_path / "calendar_token.json")
    return tmp_path


class TestTokenSurvivesARedeploy:

    def test_the_token_is_mirrored_to_turso_on_save(self, configured, monkeypatch):
        written = {}
        monkeypatch.setattr(cal_mod.turso, "is_configured", lambda: True)
        monkeypatch.setattr(cal_mod.turso, "ensure_kv_table", lambda t: None)
        monkeypatch.setattr(
            cal_mod.turso, "kv_set",
            lambda table, key, data: written.update({"table": table, "key": key, "data": data}),
        )

        friday_calendar._save_token({
            "access_token": "a", "refresh_token": "r", "expires_at": 1,
        })

        assert written["data"]["refresh_token"] == "r"

    def test_the_token_is_read_back_from_turso_when_local_disk_is_empty(
        self, configured, monkeypatch
    ):
        """The actual redeploy scenario: fresh container, no local file,
        but the boss authorized before the deploy."""
        monkeypatch.setattr(cal_mod, "TOKEN_FILE", configured / "gone.json")
        monkeypatch.setattr(cal_mod.turso, "is_configured", lambda: True)
        monkeypatch.setattr(cal_mod.turso, "ensure_kv_table", lambda t: None)
        monkeypatch.setattr(
            cal_mod.turso, "kv_get",
            lambda table, key: {
                "access_token": "survived", "refresh_token": "survived-refresh",
                "expires_at": time.time() + 3600,
            },
        )

        assert friday_calendar.is_connected() is True
        assert friday_calendar._get_access_token() == "survived"

    def test_a_turso_outage_falls_back_to_local_disk_rather_than_breaking(
        self, configured, monkeypatch
    ):
        """Turso being down must not take the calendar down with it when
        the local copy is right there."""
        token_file = configured / "calendar_token.json"
        token_file.write_text(json.dumps({
            "access_token": "local-copy", "refresh_token": "local-refresh",
            "expires_at": time.time() + 3600,
        }))

        monkeypatch.setattr(cal_mod.turso, "is_configured", lambda: True)
        monkeypatch.setattr(cal_mod.turso, "ensure_kv_table", lambda t: None)
        monkeypatch.setattr(
            cal_mod.turso, "kv_get",
            mock.Mock(side_effect=RuntimeError("turso unreachable")),
        )

        assert friday_calendar._get_access_token() == "local-copy"

    def test_a_refreshed_access_token_is_persisted_to_both_stores(
        self, configured, monkeypatch
    ):
        """The refresh path reads the stored token, updates it, and saves
        it back -- if that round trip dropped the Turso mirror, the
        connection would still die on the next redeploy despite the
        mirror existing."""
        token_file = configured / "calendar_token.json"
        token_file.write_text(json.dumps({
            "access_token": "stale", "refresh_token": "refresh-me",
            "expires_at": time.time() - 10,   # expired
        }))

        written = {}
        monkeypatch.setattr(cal_mod.turso, "is_configured", lambda: True)
        monkeypatch.setattr(cal_mod.turso, "ensure_kv_table", lambda t: None)
        monkeypatch.setattr(cal_mod.turso, "kv_get", lambda table, key: None)
        monkeypatch.setattr(
            cal_mod.turso, "kv_set",
            lambda table, key, data: written.update(data),
        )

        fake = mock.Mock(
            status_code=200,
            json=lambda: {"access_token": "fresh", "expires_in": 3600},
        )
        with mock.patch("httpx.post", lambda url, **kw: fake):
            token = friday_calendar._get_access_token()

        assert token == "fresh"
        assert written["access_token"] == "fresh"
        # The refresh token has to survive the round trip too, or the
        # next refresh has nothing to work with.
        assert written["refresh_token"] == "refresh-me"
        assert json.loads(token_file.read_text())["access_token"] == "fresh"
