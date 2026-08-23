"""tests/test_verification_engine.py — V3 migration Phase 13. Each
verify_*() function is tested against what its real call site actually
passes it (see routes/email.py, routes/security.py,
core/self_repair.py) rather than an idealized/hypothetical shape.
"""
from unittest import mock

from core.verification_engine import (
    VerificationStatus,
    verify_email_sent,
    verify_hulkbuster_deploy,
    verify_self_repair_apply,
)


class TestVerifyEmailSent:
    def test_ok_result_is_verified(self):
        result = verify_email_sent({"ok": True, "to": "a@b.com"})
        assert result.status == VerificationStatus.VERIFIED
        assert result.ok is True
        assert "a@b.com" in result.detail

    def test_failed_send_is_failed_not_verified(self):
        result = verify_email_sent({"ok": False, "error": "auth failed"})
        assert result.status == VerificationStatus.FAILED
        assert result.ok is False
        assert "auth failed" in result.detail

    def test_to_dict_shape(self):
        d = verify_email_sent({"ok": True, "to": "a@b.com"}).to_dict()
        assert d == {"status": "verified", "detail": mock.ANY, "verified": True}


class TestVerifyHulkbusterDeploy:
    def test_no_ip_is_unverifiable_not_silently_verified(self):
        result = verify_hulkbuster_deploy({"deployed": True})
        assert result.status == VerificationStatus.UNVERIFIABLE
        assert result.ok is False

    def test_ip_present_in_live_blocklist_is_verified(self):
        with mock.patch("services.friday_security.friday_security._blocked_ips", {"1.2.3.4"}):
            result = verify_hulkbuster_deploy({"deployed": True, "ip": "1.2.3.4", "ip_blocked": True})
        assert result.status == VerificationStatus.VERIFIED

    def test_ip_absent_from_live_blocklist_is_failed_despite_ip_blocked_flag(self):
        """The core point of this function: don't trust deploy()'s own
        ip_blocked flag alone -- independently re-check."""
        with mock.patch("services.friday_security.friday_security._blocked_ips", set()):
            result = verify_hulkbuster_deploy({"deployed": True, "ip": "1.2.3.4", "ip_blocked": True})
        assert result.status == VerificationStatus.FAILED
        assert "1.2.3.4" in result.detail

    def test_check_failure_is_unverifiable_not_a_crash(self):
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "services.friday_security":
                raise ImportError("simulated failure")
            return real_import(name, *args, **kwargs)

        with mock.patch.object(builtins, "__import__", fake_import):
            result = verify_hulkbuster_deploy({"ip": "1.2.3.4"})
        assert result.status == VerificationStatus.UNVERIFIABLE


class TestVerifySelfRepairApply:
    def test_matching_content_that_compiles_is_verified(self, tmp_path):
        f = tmp_path / "sample.py"
        f.write_text("x = 1\n")
        result = verify_self_repair_apply(f, "x = 1\n")
        assert result.status == VerificationStatus.VERIFIED

    def test_content_mismatch_is_failed(self, tmp_path):
        f = tmp_path / "sample.py"
        f.write_text("x = 1\n")
        result = verify_self_repair_apply(f, "x = 2\n")
        assert result.status == VerificationStatus.FAILED
        assert "match" in result.detail

    def test_invalid_syntax_is_failed_even_if_content_matches(self, tmp_path):
        f = tmp_path / "sample.py"
        f.write_text("def(((invalid")
        result = verify_self_repair_apply(f, "def(((invalid")
        assert result.status == VerificationStatus.FAILED
        assert "compile" in result.detail

    def test_unreadable_file_is_failed_not_a_crash(self, tmp_path):
        missing = tmp_path / "does_not_exist.py"
        result = verify_self_repair_apply(missing, "x = 1")
        assert result.status == VerificationStatus.FAILED
