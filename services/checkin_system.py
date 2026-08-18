"""services/checkin_system.py — "are you safe, boss?" loop for FRIDAY's
escalation paths (critical health thresholds, Mayday). A single shared
Event stands in for per-incident tracking — this repo only needs to know
whether *some* escalation is still awaiting confirmation, not which one,
so a SAFE_TRIGGERS reply stands down whatever's pending rather than
needing to be matched back to a specific incident id.
"""
import threading

# Set when an escalation fires, cleared by confirm_safe(). Any pending
# followup thread (see services/friday_health.py's _escalate_critical)
# checks this before firing its "no response" alert.
emergency_pending = threading.Event()


class CheckinSystem:

    def request_checkin(self, reason: str = "") -> dict:
        try:
            from services.notifications import critical
            critical("FRIDAY Check-In", reason or "Boss, checking in — are you safe?")
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
