"""core/verification_engine.py — V3 migration Phase 13: OBSERVE-then-
VERIFY for actions where "the function returned without raising" and
"the thing actually happened" aren't the same claim.

Scoped to three real call sites where that gap is genuine, not
hypothetical — not a generic framework for hypothetical future actions.
Extend by adding another verify_*() function alongside these, wired into
a real call site, not by building an abstract plugin system nothing
calls yet:

- Email send (services/friday_gmail.py) — the Gmail API either returns
  ok or it doesn't; there's no delivery-receipt API here to check
  further, so verification is honest about that ceiling: VERIFIED means
  "Gmail accepted it for delivery," not "it arrived."
- HulkBuster deploy (services/hulkbuster.py) — deploy()'s own
  ip_blocked flag only reflects "the try block didn't raise," not "the
  IP is actually in the blocklist right now." verify_hulkbuster_deploy
  re-checks the live set independently — a real OBSERVE step, not a
  re-read of the same try/except result.
- Self-repair apply (core/self_repair.py) — confirm_repair() previously
  wrote the fix and returned applied=True with no check that the write
  actually landed correctly on disk. verify_self_repair_apply re-reads
  the file and re-compiles it; core/self_repair.py rolls back to the
  pre-fix content automatically on a FAILED result rather than leaving
  a live file in an unknown state.
"""
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    FAILED = "failed"
    # No way to check further than "no exception was raised" -- said
    # plainly, not silently treated as VERIFIED.
    UNVERIFIABLE = "unverifiable"


@dataclass
class VerificationResult:
    status: VerificationStatus
    detail: str

    @property
    def ok(self) -> bool:
        return self.status == VerificationStatus.VERIFIED

    def to_dict(self) -> dict:
        return {"status": self.status.value, "detail": self.detail, "verified": self.ok}


def verify_email_sent(send_result: dict) -> VerificationResult:
    """send_email()'s {"ok": bool, "error": ...} is already the only
    signal the Gmail API offers here — no delivery webhook. This doesn't
    invent depth that isn't there; it standardizes that existing signal
    and says plainly that VERIFIED here means "accepted for delivery,"
    not "delivered."
    """
    if send_result.get("ok"):
        return VerificationResult(
            VerificationStatus.VERIFIED,
            f"Gmail accepted for delivery to {send_result.get('to', '?')}",
        )
    return VerificationResult(VerificationStatus.FAILED, send_result.get("error", "send failed"))


def verify_hulkbuster_deploy(deploy_result: dict) -> VerificationResult:
    ip = deploy_result.get("ip", "")
    if not ip:
        return VerificationResult(VerificationStatus.UNVERIFIABLE, "no IP given — nothing to independently verify")
    try:
        from services.friday_security import friday_security
        if ip in friday_security._blocked_ips:
            return VerificationResult(VerificationStatus.VERIFIED, f"{ip} confirmed present in the live blocklist")
        return VerificationResult(
            VerificationStatus.FAILED,
            f"{ip} is NOT in the live blocklist despite deploy() reporting "
            f"ip_blocked={deploy_result.get('ip_blocked')}",
        )
    except Exception as e:
        return VerificationResult(VerificationStatus.UNVERIFIABLE, f"couldn't check the live blocklist: {e}")


def verify_self_repair_apply(path: Path, expected_content: str) -> VerificationResult:
    try:
        on_disk = path.read_text()
    except Exception as e:
        return VerificationResult(VerificationStatus.FAILED, f"couldn't re-read the file after writing it: {e}")

    if on_disk != expected_content:
        return VerificationResult(
            VerificationStatus.FAILED,
            "file on disk doesn't match what was written — write may have partially failed",
        )

    compile_check = subprocess.run(
        [sys.executable, "-m", "py_compile", str(path)],
        capture_output=True, text=True, timeout=10,
    )
    if compile_check.returncode != 0:
        return VerificationResult(
            VerificationStatus.FAILED,
            f"live file fails to compile after write: {compile_check.stderr[-500:]}",
        )

    return VerificationResult(VerificationStatus.VERIFIED, "live file matches the applied fix and compiles cleanly")
