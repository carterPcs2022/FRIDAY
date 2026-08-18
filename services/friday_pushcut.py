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

── Free-tier fallback (call_mom) ─────────────────────────────────────────
Automation Server needs Pushcut Pro/Plus. Until that's active, call()
above won't work. call_mom() is a stopgap: Pushcut's free tier still
supports firing a *static* notification via webhook, just not with
dynamic input (who to call), so it can't generically dial "whoever
FRIDAY says" — only a single pre-configured target, set up once in the
Pushcut app itself (a "Call Mom" shortcut with the number hardcoded, and
a "Call Mom" notification linked to it). Tapping that notification on
the phone is what actually places the call — this only fires the
notification, it can't complete the call without that tap. Drop
call_mom() once Pro/Plus is active and call()/run_shortcut() cover this
generically instead.
"""
import os

import httpx

PUSHCUT_API_KEY = os.getenv("PUSHCUT_API_KEY", "")
CALL_SHORTCUT_NAME = os.getenv("PUSHCUT_CALL_SHORTCUT", "FRIDAY Call")
MOM_WEBHOOK_URL = os.getenv("PUSHCUT_MOM_WEBHOOK_URL", "")

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


def call_mom() -> dict:
    """Free-tier stopgap — see module docstring. Fires the pre-configured
    'Call Mom' notification; only completes if he taps it on his phone."""
    if not MOM_WEBHOOK_URL:
        return {"ok": False, "error": "PUSHCUT_MOM_WEBHOOK_URL not configured"}
    try:
        r = httpx.post(MOM_WEBHOOK_URL, timeout=10)
        r.raise_for_status()
        return {"ok": True, "message": "Sent, boss — tap the notification on your phone to actually call her."}
    except httpx.HTTPStatusError as e:
        return {"ok": False, "error": f"Pushcut rejected the request: {e.response.status_code} {e.response.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
