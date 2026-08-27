"""tests/test_friday_gmail_send.py — coverage for send_email() going over
the Gmail API (HTTPS) instead of raw SMTP.

Replaces the former tests/test_friday_gmail_smtp.py, whose subject matter
(_force_ipv4, per-call vs. overall SMTP timeouts, the thread/deadline
apparatus) no longer exists: confirmed live from the Render deploy,
outbound TCP to smtp.gmail.com hangs to the connect timeout on both 465
and 587, so sending moved to the Gmail API over port 443 and all of that
SMTP-specific machinery went with it.

The IPv4-forcing and wall-clock-deadline tests aren't ported because
there's nothing left for them to test, not because the behavior stopped
mattering -- a single httpx request has one timeout that genuinely bounds
the whole operation, with no multi-stage compounding to work around.
"""
import base64
import email as email_mod
import json
import time
from unittest import mock

import pytest

import services.friday_gmail as friday_gmail_mod
from services.friday_gmail import friday_gmail


@pytest.fixture
def connected(monkeypatch, tmp_path):
    """A fully OAuth-connected send path, with a live (unexpired) access
    token, writing to a throwaway token file rather than the real
    memory/ one."""
    token_file = tmp_path / "friday_gmail_send_token.json"
    token_file.write_text(json.dumps({
        "access_token": "access-token-123",
        "refresh_token": "refresh-token-456",
        "expires_at": time.time() + 3600,
    }))
    monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_TOKEN_FILE", token_file)
    monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_CLIENT_ID", "client-id")
    monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_REDIRECT_URI", "https://example.com/friday/gmail/callback")
    monkeypatch.setattr(friday_gmail_mod, "GMAIL_USER", "me@example.com")
    return token_file


class _FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class TestTheMessageActuallyPutOnTheWire:
    """The real risk in swapping transports isn't "does the mock get
    called" -- it's whether the message Gmail receives is still the
    message the boss asked for. These decode the actual base64url payload
    back into an email and check its real content, rather than asserting
    against the same dict the code just built."""

    def test_recipient_subject_and_body_survive_the_encoding(self, connected):
        sent = {}

        def fake_post(url, **kwargs):
            sent["url"] = url
            sent["json"] = kwargs.get("json")
            sent["headers"] = kwargs.get("headers")
            return _FakeResponse()

        with mock.patch("httpx.post", fake_post):
            result = friday_gmail.send_email(
                to="Pepper <pepper@example.com>",
                subject="Suit diagnostics",
                body="Mark 50 is showing a power fluctuation, boss.",
            )

        assert result["ok"] is True
        assert sent["url"] == "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
        assert sent["headers"]["Authorization"] == "Bearer access-token-123"

        # Decode what Gmail would actually receive and parse it back.
        raw = base64.urlsafe_b64decode(sent["json"]["raw"])
        msg = email_mod.message_from_bytes(raw)
        assert msg["To"] == "pepper@example.com"
        assert msg["Subject"] == "Suit diagnostics"
        assert msg["From"] == "me@example.com"
        body = "".join(
            part.get_payload(decode=True).decode()
            for part in msg.walk()
            if part.get_content_type() == "text/plain"
        )
        assert "power fluctuation" in body

    def test_the_payload_uses_base64url_not_standard_base64(self, connected):
        """Gmail's messages.send requires the raw message base64*url*
        encoded. The two alphabets agree on almost all content -- they
        differ only where standard base64 would emit '+' or '/' -- so an
        ordinary round-trip assertion can't tell them apart, and the
        content-decoding tests above would keep passing if someone
        "simplified" urlsafe_b64encode to b64encode. This body ('~~') is
        picked specifically because it does force a '+' under the standard
        alphabet, making the difference observable: the invariant asserted
        here is base64url's defining property, that neither character can
        appear in the output.
        """
        sent = {}

        def fake_post(url, **kwargs):
            sent["json"] = kwargs.get("json")
            return _FakeResponse()

        with mock.patch("httpx.post", fake_post):
            result = friday_gmail.send_email(to="a@b.com", subject="s", body="~~")

        assert result["ok"] is True
        raw_field = sent["json"]["raw"]
        assert "+" not in raw_field and "/" not in raw_field
        # Still has to be decodable back to the real message, not merely
        # free of those two characters.
        msg = email_mod.message_from_bytes(base64.urlsafe_b64decode(raw_field))
        assert msg["To"] == "a@b.com"

    def test_reply_threading_headers_survive_the_encoding(self, connected):
        """in_reply_to is what keeps a reply threaded onto the original
        instead of landing as an unrelated new message."""
        sent = {}

        def fake_post(url, **kwargs):
            sent["json"] = kwargs.get("json")
            return _FakeResponse()

        with mock.patch("httpx.post", fake_post):
            friday_gmail.send_email(
                to="a@b.com", subject="Re: hi", body="replying",
                in_reply_to="<original-message-id@mail.gmail.com>",
            )

        raw = base64.urlsafe_b64decode(sent["json"]["raw"])
        msg = email_mod.message_from_bytes(raw)
        assert msg["In-Reply-To"] == "<original-message-id@mail.gmail.com>"
        assert msg["References"] == "<original-message-id@mail.gmail.com>"

    def test_attachments_survive_the_encoding(self, connected, tmp_path):
        attachment = tmp_path / "diagnostics.txt"
        attachment.write_text("arc reactor output nominal")

        sent = {}

        def fake_post(url, **kwargs):
            sent["json"] = kwargs.get("json")
            return _FakeResponse()

        with mock.patch("httpx.post", fake_post):
            result = friday_gmail.send_email(
                to="a@b.com", subject="Report", body="See attached.",
                attachments=[str(attachment)],
            )

        assert result["ok"] is True
        assert result["attachments"] == ["diagnostics.txt"]

        raw = base64.urlsafe_b64decode(sent["json"]["raw"])
        msg = email_mod.message_from_bytes(raw)
        attached = [
            part for part in msg.walk()
            if part.get_filename() == "diagnostics.txt"
        ]
        assert len(attached) == 1
        assert attached[0].get_payload(decode=True) == b"arc reactor output nominal"


class TestFailuresAreReportedHonestly:
    """#16's lesson, kept: a send that didn't happen must never come back
    looking like one that did."""

    def test_an_api_error_is_a_failure_not_a_silent_success(self, connected):
        with mock.patch("httpx.post", lambda url, **kw: _FakeResponse(403, "insufficient scope")):
            result = friday_gmail.send_email(to="a@b.com", subject="hi", body="test")

        assert result["ok"] is False
        assert "403" in result["error"]

    def test_a_network_exception_is_a_failure_not_a_silent_success(self, connected):
        with mock.patch("httpx.post", mock.Mock(side_effect=RuntimeError("connection reset"))):
            result = friday_gmail.send_email(to="a@b.com", subject="hi", body="test")

        assert result["ok"] is False
        assert "connection reset" in result["error"]

    def test_not_connected_refuses_without_making_a_request(self, monkeypatch, tmp_path):
        """Before OAuth is completed there's no token to send with --
        this must fail closed rather than firing an unauthenticated
        request at Gmail."""
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_TOKEN_FILE", tmp_path / "missing.json")
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_CLIENT_ID", "client-id")
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_CLIENT_SECRET", "client-secret")
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_REDIRECT_URI", "https://example.com/cb")

        posted = mock.Mock()
        with mock.patch("httpx.post", posted):
            result = friday_gmail.send_email(to="a@b.com", subject="hi", body="test")

        assert result["ok"] is False
        assert "/friday/gmail/auth" in result["error"]
        posted.assert_not_called()

    def test_a_bad_address_is_rejected_before_any_request(self, connected):
        posted = mock.Mock()
        with mock.patch("httpx.post", posted):
            result = friday_gmail.send_email(to="not-an-address", subject="hi", body="test")

        assert result["ok"] is False
        posted.assert_not_called()

    def test_an_empty_body_is_rejected_before_any_request(self, connected):
        posted = mock.Mock()
        with mock.patch("httpx.post", posted):
            result = friday_gmail.send_email(to="a@b.com", subject="hi", body="   ")

        assert result["ok"] is False
        posted.assert_not_called()

    def test_a_missing_attachment_is_rejected_before_any_request(self, connected):
        """A file the boss asked to attach that quietly never showed up is
        worse than a failed send -- so this stays a hard error."""
        posted = mock.Mock()
        with mock.patch("httpx.post", posted):
            result = friday_gmail.send_email(
                to="a@b.com", subject="hi", body="test",
                attachments=["nothing-by-this-name"],
            )

        assert result["ok"] is False
        assert "not found" in result["error"].lower()
        posted.assert_not_called()


class TestTokenRefresh:

    def test_an_expired_access_token_is_refreshed_before_sending(self, monkeypatch, tmp_path):
        token_file = tmp_path / "token.json"
        token_file.write_text(json.dumps({
            "access_token": "stale-token",
            "refresh_token": "refresh-token-456",
            "expires_at": time.time() - 10,   # already expired
        }))
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_TOKEN_FILE", token_file)
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_CLIENT_ID", "client-id")
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_CLIENT_SECRET", "client-secret")
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_REDIRECT_URI", "https://example.com/cb")

        calls = []

        def fake_post(url, **kwargs):
            calls.append((url, kwargs))
            if "oauth2.googleapis.com" in url:
                return mock.Mock(
                    status_code=200,
                    json=lambda: {"access_token": "fresh-token", "expires_in": 3600},
                )
            return _FakeResponse()

        with mock.patch("httpx.post", fake_post):
            result = friday_gmail.send_email(to="a@b.com", subject="hi", body="test")

        assert result["ok"] is True
        assert "oauth2.googleapis.com" in calls[0][0]
        # The send must use the *refreshed* token, not the stale one.
        assert calls[1][1]["headers"]["Authorization"] == "Bearer fresh-token"
        # And the refreshed token is persisted, so the next send doesn't
        # have to round-trip through Google again.
        assert json.loads(token_file.read_text())["access_token"] == "fresh-token"

    def test_a_failed_refresh_fails_the_send_rather_than_sending_unauthenticated(
        self, monkeypatch, tmp_path
    ):
        token_file = tmp_path / "token.json"
        token_file.write_text(json.dumps({
            "access_token": "stale-token",
            "refresh_token": "revoked-refresh-token",
            "expires_at": time.time() - 10,
        }))
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_TOKEN_FILE", token_file)
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_CLIENT_ID", "client-id")
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_CLIENT_SECRET", "client-secret")
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_REDIRECT_URI", "https://example.com/cb")

        sent_urls = []

        def fake_post(url, **kwargs):
            sent_urls.append(url)
            # Refresh rejected (e.g. the boss revoked access in their
            # Google account).
            return _FakeResponse(400, "invalid_grant")

        with mock.patch("httpx.post", fake_post):
            result = friday_gmail.send_email(to="a@b.com", subject="hi", body="test")

        assert result["ok"] is False
        # Only the refresh was attempted -- no send went out without a
        # valid token.
        assert all("oauth2.googleapis.com" in u for u in sent_urls)


class TestTokenSurvivesARedeploy:
    """render.yaml mounts no disk, so memory/ is ephemeral: a token kept
    only on local disk is gone on every redeploy and every free-tier idle
    spin-down, which would mean re-running the consent flow constantly
    and would read as "sending is broken again". The Turso mirror is what
    makes the connection actually persist, so it's tested rather than
    assumed."""

    def test_the_token_is_mirrored_to_turso_on_save(self, monkeypatch, tmp_path):
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_TOKEN_FILE", tmp_path / "token.json")
        written = {}

        monkeypatch.setattr(friday_gmail_mod.turso, "is_configured", lambda: True)
        monkeypatch.setattr(friday_gmail_mod.turso, "ensure_kv_table", lambda t: None)
        monkeypatch.setattr(
            friday_gmail_mod.turso, "kv_set",
            lambda table, key, data: written.update({"table": table, "key": key, "data": data}),
        )

        friday_gmail._save_send_token({"refresh_token": "r", "access_token": "a", "expires_at": 1})

        assert written["data"]["refresh_token"] == "r"

    def test_the_token_is_read_back_from_turso_when_local_disk_is_empty(
        self, monkeypatch, tmp_path
    ):
        """The actual redeploy scenario: fresh container, no local file,
        but the boss authorized before the deploy."""
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_TOKEN_FILE", tmp_path / "gone.json")
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_CLIENT_ID", "client-id")
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_CLIENT_SECRET", "client-secret")
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_REDIRECT_URI", "https://example.com/cb")

        monkeypatch.setattr(friday_gmail_mod.turso, "is_configured", lambda: True)
        monkeypatch.setattr(friday_gmail_mod.turso, "ensure_kv_table", lambda t: None)
        monkeypatch.setattr(
            friday_gmail_mod.turso, "kv_get",
            lambda table, key: {
                "access_token": "survived", "refresh_token": "survived-refresh",
                "expires_at": time.time() + 3600,
            },
        )

        assert friday_gmail.send_is_connected() is True
        assert friday_gmail._get_send_access_token() == "survived"

    def test_a_turso_outage_falls_back_to_local_disk_rather_than_breaking(
        self, monkeypatch, tmp_path
    ):
        """Turso being down must not take sending down with it when the
        local copy is right there -- same defensive shape as
        friday_habits.py."""
        token_file = tmp_path / "token.json"
        token_file.write_text(json.dumps({
            "access_token": "local-copy", "refresh_token": "local-refresh",
            "expires_at": time.time() + 3600,
        }))
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_TOKEN_FILE", token_file)

        monkeypatch.setattr(friday_gmail_mod.turso, "is_configured", lambda: True)
        monkeypatch.setattr(friday_gmail_mod.turso, "ensure_kv_table", lambda t: None)
        monkeypatch.setattr(
            friday_gmail_mod.turso, "kv_get",
            mock.Mock(side_effect=RuntimeError("turso unreachable")),
        )

        assert friday_gmail._get_send_access_token() == "local-copy"


class TestOAuthConnectionState:

    def test_configured_requires_all_three_credentials(self, monkeypatch, tmp_path):
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_TOKEN_FILE", tmp_path / "t.json")
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_CLIENT_ID", "client-id")
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_CLIENT_SECRET", "client-secret")
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_REDIRECT_URI", "")
        assert friday_gmail.send_is_configured() is False

        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_REDIRECT_URI", "https://example.com/cb")
        assert friday_gmail.send_is_configured() is True

    def test_configured_but_not_yet_authorized_is_not_connected(self, monkeypatch, tmp_path):
        """The distinction that matters for the setup flow: credentials
        present, but the boss hasn't been through the consent screen."""
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_TOKEN_FILE", tmp_path / "missing.json")
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_CLIENT_ID", "client-id")
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_CLIENT_SECRET", "client-secret")
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_REDIRECT_URI", "https://example.com/cb")

        assert friday_gmail.send_is_configured() is True
        assert friday_gmail.send_is_connected() is False

    def test_auth_url_carries_the_send_scope_and_offline_access(self, monkeypatch):
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_CLIENT_ID", "client-id")
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_REDIRECT_URI", "https://example.com/cb")
        url = friday_gmail.send_auth_url()

        assert "gmail.send" in url
        # Without offline access + forced consent there's no refresh
        # token, and the connection would silently die in an hour.
        assert "access_type=offline" in url
        assert "prompt=consent" in url

    def test_exchange_code_persists_the_refresh_token(self, monkeypatch, tmp_path):
        token_file = tmp_path / "token.json"
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_TOKEN_FILE", token_file)
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_CLIENT_ID", "client-id")
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_CLIENT_SECRET", "client-secret")
        monkeypatch.setattr(friday_gmail_mod, "GMAIL_SEND_REDIRECT_URI", "https://example.com/cb")

        fake = mock.Mock(
            status_code=200,
            json=lambda: {
                "access_token": "new-access", "refresh_token": "new-refresh",
                "expires_in": 3600,
            },
        )
        with mock.patch("httpx.post", lambda url, **kw: fake):
            result = friday_gmail.send_exchange_code("auth-code-from-google")

        assert result == {"ok": True}
        saved = json.loads(token_file.read_text())
        assert saved["refresh_token"] == "new-refresh"
        assert friday_gmail.send_is_connected() is True
