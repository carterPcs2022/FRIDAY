"""tests/test_friday_gmail_read.py — services/friday_gmail.py's IMAP read
path (connect()/get_unread()).

connect() previously built imaplib.IMAP4_SSL with no timeout at all.
This module's own docstring documents that raw SMTP hangs to the connect
timeout on this Render host's outbound network (a common anti-abuse
block on non-HTTPS ports) -- confirmed live, which is why send_email()
moved to the Gmail API over HTTPS. IMAP still runs over the same kind of
raw, non-443 connection for reading, and unlike SMTP it had no timeout
set, so the same class of network block would hang forever instead of
failing fast.

This is almost certainly the "1 of 3 futures unfinished" hang
_cmd_catchup's own comments flagged as unidentified: get_unread() is the
only one of catchup's three parallel calls with a genuinely unbounded
network operation -- who_needs_attention() is pure in-memory, and
morning_brief()'s search + model calls are all bounded somewhere
(core/tools/search.py's per-provider timeout, Groq's httpx.Timeout).
"""
from unittest import mock

import services.friday_gmail as gmail_mod
from services.friday_gmail import friday_gmail


class TestConnectHasABoundedTimeout:

    def test_imap4_ssl_is_given_an_explicit_timeout(self, monkeypatch):
        monkeypatch.setattr(gmail_mod, "GMAIL_USER", "boss@example.com")
        monkeypatch.setattr(gmail_mod, "GMAIL_PASS", "app-password")

        fake_imap = mock.Mock()
        fake_ctor = mock.Mock(return_value=fake_imap)
        with mock.patch.object(gmail_mod.imaplib, "IMAP4_SSL", fake_ctor):
            friday_gmail.connect()

        assert fake_ctor.call_count == 1
        _, kwargs = fake_ctor.call_args
        assert kwargs.get("timeout") is not None
        assert kwargs["timeout"] > 0
        # Not just present -- actually finite and reasonable, so a
        # genuinely stuck connection still fails inside catchup's own
        # 15-second budget rather than merely "eventually."
        assert kwargs["timeout"] <= 15

    def test_get_unread_does_not_hang_when_connect_itself_times_out(self, monkeypatch):
        """The realistic failure this guards against: the connection
        attempt itself times out (imaplib raises on the socket timeout),
        not just a slow-but-successful login. Must come back as an empty
        list, the same as any other IMAP failure, not propagate and take
        the caller down with it."""
        monkeypatch.setattr(gmail_mod, "GMAIL_USER", "boss@example.com")
        monkeypatch.setattr(gmail_mod, "GMAIL_PASS", "app-password")

        import socket
        with mock.patch.object(gmail_mod.imaplib, "IMAP4_SSL",
                                side_effect=socket.timeout("timed out")):
            result = friday_gmail.get_unread(10)

        assert result == []
