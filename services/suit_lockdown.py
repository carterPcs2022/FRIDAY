"""services/suit_lockdown.py — remote panic-disable if the phone or Mac
this account normally runs from is lost or stolen. Deliberately has no
in-app backdoor: unlocking requires knowing ENDGAME_PASSPHRASE, checked
directly against the raw message with no trigger word needed (an earlier
design that required stripping an "unlock " prefix off the message before
comparing was the actual bug — the extraction was never implemented, so
the correct passphrase typed after "unlock " would never match the bare
passphrase and the system could never be unlocked through chat again).
Recovery when the passphrase itself is lost is intentionally a deploy-time
action, not a runtime one — see RESET_LOCKDOWN below.
"""
import json
import os
from pathlib import Path
from datetime import datetime

LOCKDOWN_FILE = Path("memory/lockdown_state.json")


class SuitLockdown:

    def __init__(self):
        self._state = self._load()
        # Deploy-time recovery: set RESET_LOCKDOWN=true on Render, restart
        # once, then unset it. Checked only here at construction (a boot
        # -time action), never inside a request handler — there is no
        # chat-triggerable way to clear a lockdown other than the correct
        # passphrase, by design.
        if self._state.get("locked") and os.getenv("RESET_LOCKDOWN", "").lower() == "true":
            print("[Suit Lockdown] RESET_LOCKDOWN=true — clearing lockdown state at startup.")
            self._state["locked"] = False
            self._state["reset_at"] = datetime.now().isoformat()
            self._save()
        elif self._state.get("locked"):
            print(f"[Suit Lockdown] LOCKED at startup — reason: {self._state.get('reason', 'unknown')}, "
                  f"since {self._state.get('locked_at', 'unknown')}. "
                  f"To recover without the passphrase: set RESET_LOCKDOWN=true and redeploy.")

    def activate(self, reason: str = "manual") -> dict:
        self._state["locked"] = True
        self._state["locked_at"] = datetime.now().isoformat()
        self._state["reason"] = reason
        self._save()

        try:
            import httpx
            httpx.post(
                "https://api.pushover.net/1/messages.json",
                data={
                    "token": os.getenv("PUSHOVER_APP_TOKEN", ""),
                    "user": os.getenv("PUSHOVER_USER_KEY", ""),
                    "title": "FRIDAY — LOCKDOWN ACTIVE",
                    "message": f"System locked. Reason: {reason}. Re-authenticate to restore access.",
                    "priority": 1,
                }, timeout=5,
            )
        except Exception:
            pass

        return {"locked": True, "reason": reason}

    def try_unlock(self, message: str) -> bool:
        """No trigger word, no prefix stripping — the raw message must
        equal the passphrase (case-insensitive, whitespace-trimmed)."""
        correct = os.getenv("ENDGAME_PASSPHRASE", "")
        if not correct:
            return False
        if message.strip().lower() == correct.strip().lower():
            self._state["locked"] = False
            self._state["unlocked_at"] = datetime.now().isoformat()
            self._save()
            return True
        return False

    def is_locked(self) -> bool:
        return self._state.get("locked", False)

    def _load(self) -> dict:
        if LOCKDOWN_FILE.exists():
            try:
                return json.loads(LOCKDOWN_FILE.read_text())
            except Exception:
                return {}
        return {}

    def _save(self):
        LOCKDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOCKDOWN_FILE.write_text(json.dumps(self._state, indent=2))


suit_lockdown = SuitLockdown()
