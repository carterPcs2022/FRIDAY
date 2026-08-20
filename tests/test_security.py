"""tests/test_security.py — regression coverage for the two
services/friday_security.py fixes from earlier today: the spoofable
client-IP trust (ProxyFix) and IP blocks that didn't survive a restart
(Turso-backed persistence).
"""
from unittest import mock

from services.friday_security import FridaySecurity


class TestProxyFixClientIP:
    """server.py wraps the app in werkzeug's ProxyFix(x_for=1), which
    trusts exactly one hop counted from the *right* (the proxy's own
    X-Forwarded-For addition) rather than the client-controlled first
    entry -- so request.remote_addr is already correct by the time
    client_ip() reads it (a plain `return request.remote_addr or
    "unknown"`, no header re-parsing of its own).

    Verified against a standalone app configured identically to
    server.py's real ProxyFix call, rather than the shared `app` fixture
    -- registering a new route on that fixture fails once any other test
    has already sent it a request (Flask locks setup after first
    request), and test_request_context() doesn't run the WSGI middleware
    stack at all, so neither can exercise this end-to-end."""

    def _build_proxied_app(self):
        from flask import Flask, request
        from werkzeug.middleware.proxy_fix import ProxyFix

        probe = Flask(__name__)
        probe.wsgi_app = ProxyFix(probe.wsgi_app, x_for=1, x_proto=1, x_host=0, x_port=0, x_prefix=0)

        @probe.route("/whoami")
        def _whoami():
            fs = FridaySecurity()
            return fs.client_ip(request)

        return probe

    def test_proxyfix_prefers_rightmost_hop_over_spoofed_first_entry(self):
        client = self._build_proxied_app().test_client()
        resp = client.get("/whoami", headers={"X-Forwarded-For": "6.6.6.6, 203.0.113.9"})
        assert resp.data.decode() == "203.0.113.9", (
            "ProxyFix should trust the proxy-appended (rightmost) hop, not "
            f"the attacker-controlled first entry; got {resp.data.decode()!r}"
        )

    def test_no_forwarded_header_falls_back_to_direct_peer(self):
        client = self._build_proxied_app().test_client()
        resp = client.get("/whoami")
        assert resp.data.decode() not in ("", "unknown")


class TestBlockPersistence:
    def test_rate_limit_block_is_persisted_and_reloaded(self):
        store = {}

        class FakeTurso:
            @staticmethod
            def is_configured():
                return True

            @staticmethod
            def ensure_kv_table(_table):
                pass

            @staticmethod
            def kv_set(_table, key, data):
                store[key] = data

            @staticmethod
            def kv_all(_table):
                return dict(store)

        with mock.patch("db.turso_http_client", FakeTurso):
            fs1 = FridaySecurity()
            for _ in range(31):
                result = fs1.screen_request("9.9.9.9", "hello")
            assert result == {"blocked": True, "reason": "rate_limit"}
            assert "9.9.9.9" in store

            # Simulates a redeploy: a brand-new process should pick the
            # block back up from Turso instead of starting clean.
            fs2 = FridaySecurity()
            assert "9.9.9.9" in fs2._blocked_ips
            assert fs2.screen_request("9.9.9.9", "hello again") == {
                "blocked": True, "reason": "blocked_ip",
            }

    def test_unconfigured_turso_falls_back_to_in_memory_only(self):
        class UnconfiguredTurso:
            @staticmethod
            def is_configured():
                return False

        with mock.patch("db.turso_http_client", UnconfiguredTurso):
            fs = FridaySecurity()
            for _ in range(31):
                result = fs.screen_request("1.2.3.4", "hi")
            assert result == {"blocked": True, "reason": "rate_limit"}
