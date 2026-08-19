"""services/hulkbuster.py — FRIDAY's maximum-response protocol.

Two callers deploy it, same as the source material: friday_security.py
(a request pattern that stops looking like noise and starts looking like
a real attempt — several injection/probe attempts from one IP in a short
window) and core/veronica.py (a security file itself — friday_security.py
or suit_lockdown.py — turning up tampered, i.e. a firewall getting taken
apart piece by piece rather than just failing on its own).

Deploying does the two things a "strongest response" actually means for
a single-process Flask app: permanently blocks the offending IP (not
just the rolling rate-limit window) and throws suit_lockdown — the same
panic-disable a lost phone would trigger. Undoing suit_lockdown still
needs ENDGAME_PASSPHRASE either way; HulkBuster doesn't get a bypass any
more than a manual lockdown would.
"""
import json
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent
HULKBUSTER_LOG = BASE_DIR / "logs" / "hulkbuster.jsonl"


class HulkBuster:

    def __init__(self):
        self._deployed = False
        self._deploy_count = 0
        self._last = {}

    def deploy(self, reason: str, ip: str = "") -> dict:
        self._deployed = True
        self._deploy_count += 1
        entry = {
            "reason": reason, "ip": ip,
            "deployment": self._deploy_count, "ts": datetime.now().isoformat(),
        }
        self._last = entry
        self._log(entry)

        blocked = False
        if ip:
            try:
                from services.friday_security import friday_security
                friday_security._blocked_ips.add(ip)
                # Without this, a manually-triggered deploy (the
                # /friday/hulkbuster/deploy route, or core/veronica.py
                # detecting a tampered security file) only blocks the IP
                # for as long as this process stays up -- the whole point
                # of friday_security's Turso-backed persistence was that a
                # HulkBuster block survives a redeploy, not just the
                # automatic 3-threats escalation path that already calls
                # this correctly via friday_security._maybe_escalate().
                friday_security._persist_block(ip, f"hulkbuster: {reason}")
                blocked = True
            except Exception:
                pass

        locked = False
        try:
            from services.suit_lockdown import suit_lockdown
            suit_lockdown.activate(reason=f"HulkBuster deployment: {reason}")
            locked = True
        except Exception:
            pass

        self._alert(reason, ip)
        return {
            "deployed": True, "reason": reason, "ip": ip,
            "ip_blocked": blocked, "lockdown": locked, "deployment": self._deploy_count,
        }

    def stand_down(self) -> dict:
        """Clears the active-deployment flag once the boss confirms the
        threat's over. Doesn't touch suit_lockdown — that still needs
        the passphrase, same as any other lockdown, by the same
        no-in-app-backdoor reasoning suit_lockdown.py documents."""
        self._deployed = False
        return {"deployed": False}

    def status(self) -> dict:
        return {"deployed": self._deployed, "deployments": self._deploy_count, "last": self._last}

    def _alert(self, reason: str, ip: str):
        message = (
            f"HulkBuster deployed. Reason: {reason}."
            + (f" Source IP: {ip}." if ip else "")
            + " Lockdown engaged."
        )
        try:
            from services.friday_voice import speak
            speak(f"Veronica: {message}")
        except Exception:
            pass
        try:
            from services.notifications import critical
            critical("FRIDAY — HULKBUSTER DEPLOYED", message, expire=3600)
        except Exception:
            pass
        print(f"[HulkBuster] {message}")

    def _log(self, entry: dict):
        try:
            HULKBUSTER_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(HULKBUSTER_LOG, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass


hulkbuster = HulkBuster()
