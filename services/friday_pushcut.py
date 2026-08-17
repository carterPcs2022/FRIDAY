"""services/friday_pushcut.py — places a call from the boss's own
phone number, via Pushcut's Automation Server remotely running a
Shortcut on his actual iPhone. Complements services/friday_phone.py's
Twilio number rather than replacing it: Twilio gives FRIDAY her own
independent number; this makes his own phone dial, so the call
genuinely comes from his real number — no telephony API, no carrier
caller-ID verification, because FRIDAY isn't the one dialing.

Requires, on his end (not something this code can do for him):
1. A Shortcut named CALL_SHORTCUT_NAME on his iPhone, accepting Shortcut
   Input and passing it straight to the Call action.
2. Pushcut's Automation Server running on that same iPhone (Pushcut app
   -> Automation Server -> Start Server On This Device) — a Pushcut
   Pro/Plus feature.
3. A Pushcut API key (Pushcut app -> Account -> API Keys) set as
   PUSHCUT_API_KEY here.

None of that is verifiable from a server — is_configured() only confirms
the API key is present, not that the Shortcut exists or the phone is
online. A failed call here most likely means the phone's asleep/offline
or Automation Server isn't running, not a bug in this code.
"""
import os

import httpx

PUSHCUT_API_KEY = os.getenv("PUSHCUT_API_KEY", "")
CALL_SHORTCUT_NAME = os.getenv("PUSHCUT_CALL_SHORTCUT", "FRIDAY Call")

_EXECUTE_URL = "https://api.pushcut.io/v1/execute"


def is_configured() -> bool:
    return bool(PUSHCUT_API_KEY)


def run_shortcut(name: str, input_text: str = "") -> dict:
    if not PUSHCUT_API_KEY:
        return {"ok": False, "error": "Pushcut not configured (PUSHCUT_API_KEY missing)"}
    try:
        r = httpx.post(
            _EXECUTE_URL,
            headers={"API-Key": PUSHCUT_API_KEY, "Content-Type": "application/json"},
            json={"shortcut": name, "input": input_text},
            timeout=10,
        )
        r.raise_for_status()
        return {"ok": True}
    except httpx.HTTPStatusError as e:
        return {"ok": False, "error": f"Pushcut rejected the request: {e.response.status_code} {e.response.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def call(contact_or_number: str) -> dict:
    """Remotely runs his on-device CALL_SHORTCUT_NAME shortcut with the
    target as input — his phone places the call, not FRIDAY."""
    if not contact_or_number:
        return {"ok": False, "error": "No contact or number provided"}
    return run_shortcut(CALL_SHORTCUT_NAME, contact_or_number)
