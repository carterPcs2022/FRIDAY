"""tests/test_friday_gmail_smtp.py — regression coverage for the Errno 101
("Network is unreachable") fix in services/friday_gmail.py::send_email().

Confirmed live: smtp.gmail.com resolves to both IPv4 and IPv6, Render has
no outbound IPv6 route, and every send failed at the socket-connect
stage -- before ever reaching Gmail's login check (imap.gmail.com's login
over the same credentials worked fine in the same process, ruling out a
credentials problem). _force_ipv4() scopes socket.getaddrinfo to only
return IPv4 results for the duration of the SMTP connection attempt.
"""
import socket
from unittest import mock

import services.friday_gmail as friday_gmail_mod
from services.friday_gmail import friday_gmail, _force_ipv4


def test_force_ipv4_forces_af_inet_family():
    # Patched in BEFORE entering _force_ipv4() so the context manager's own
    # `original = socket.getaddrinfo` captures this fake rather than the
    # real resolver -- lets us inspect exactly what _ipv4_only() forwards
    # to it, with no real DNS lookup involved.
    fake_getaddrinfo = mock.Mock(return_value=[])
    with mock.patch.object(socket, "getaddrinfo", fake_getaddrinfo):
        with _force_ipv4():
            socket.getaddrinfo("smtp.gmail.com", 465)

    args, kwargs = fake_getaddrinfo.call_args
    family = args[2] if len(args) > 2 else kwargs.get("family")
    assert family == socket.AF_INET


def test_force_ipv4_restores_original_getaddrinfo_after_exit():
    original = socket.getaddrinfo
    with _force_ipv4():
        assert socket.getaddrinfo is not original
    assert socket.getaddrinfo is original


def test_force_ipv4_restores_original_even_on_exception():
    original = socket.getaddrinfo
    try:
        with _force_ipv4():
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert socket.getaddrinfo is original


def test_send_email_uses_force_ipv4_around_smtp_connection():
    """The actual regression: send_email() must wrap its SMTP_SSL
    connection in _force_ipv4(), not just have the helper exist unused."""
    seen_patched = {}

    class _FakeSMTP:
        def __init__(self, *a, **kw):
            # If socket.getaddrinfo isn't the patched version here,
            # _force_ipv4() isn't actually wrapping this connection.
            seen_patched["getaddrinfo_is_patched"] = socket.getaddrinfo is not _original_getaddrinfo

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, *a, **kw):
            pass

        def send_message(self, *a, **kw):
            pass

    _original_getaddrinfo = socket.getaddrinfo

    with mock.patch.object(friday_gmail_mod, "GMAIL_USER", "me@example.com"), \
         mock.patch.object(friday_gmail_mod, "GMAIL_PASS", "app-password"), \
         mock.patch.object(friday_gmail_mod.smtplib, "SMTP_SSL", _FakeSMTP):
        result = friday_gmail.send_email(to="a@b.com", subject="hi", body="test")

    assert result["ok"] is True
    assert seen_patched.get("getaddrinfo_is_patched") is True
    # And restored afterward -- no lingering process-wide patch.
    assert socket.getaddrinfo is _original_getaddrinfo
