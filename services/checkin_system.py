"""services/checkin_system.py — "are you safe, boss?" loop for FRIDAY's
escalation paths (critical health thresholds, Mayday). A single shared
Event stands in for per-incident tracking — this repo only needs to know
whether *some* escalation is still awaiting confirmation, not which one,
so a SAFE_TRIGGERS reply stands down whatever's pending rather than
needing to be matched back to a specific incident id.
"""
import os
import threading

# Set when an escalation fires, cleared by confirm_safe(). Any pending
# followup thread (see services/friday_health.py's _escalate_critical)
# checks this before firing its "no response" alert.
emergency_pending = threading.Event()


class CheckinSystem:

    def request_checkin(self, reason: str = "") -> dict:
        user = os.environ.get("PUSHOVER_USER_KEY", "")
        token = os.environ.get("PUSHOVER_APP_TOKEN", "")
        if not (user and token):
            return {"error": "Pushover not configured"}
        try:
            import httpx
            httpx.post(
                "https://api.pushover.net/1/messages.json",
                data={
                    "token": token, "user": user,
                    "title": "FRIDAY Check-In",
                    "message": reason or "Boss, checking in — are you safe?",
                    "priority": 1,
                },
                timeout=5,
            )
            emergency_pending.set()
            return {"ok": True}
        except Exception as e:
            return {"error": str(e)}

    def confirm_safe(self) -> dict:
        emergency_pending.clear()
        try:
            from services.friday_voice import speak
            speak("Good to hear, boss. Standing down.")
        except Exception:
            pass
        return {"ok": True, "status": "stood_down"}


checkin_system = CheckinSystem()
