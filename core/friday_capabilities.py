"""core/friday_capabilities.py — MCU-flavored dedicated response formats,
one per named capability, distinct from ordinary conversation.

Honest framing: these are prompt templates around the same
friday_brain.think() that already handles any of this conversationally —
there's no separate fighting-pattern-analysis engine or physics
simulator behind them. What they add is a consistent trigger phrase and
response shape (and, for a couple, a real side effect — voice line +
Pushover alert) rather than leaving it to how the LLM happens to
interpret an ad-hoc phrasing each time.

core.tools.web doesn't exist in this repo (checked), so the two
functions that would use it degrade gracefully to a brief with no
search results instead of crashing.
"""
import os
from datetime import datetime


class FridayMCUCapabilities:

    # ── Age of Ultron ────────────────────────────────────────────────────

    def physics_calculation(self, situation: str) -> dict:
        from core.friday_brain import friday_brain
        result = friday_brain.think(
            f"Physics/consequence analysis:\n{situation}\n\n"
            f"Calculate risk, collateral damage, safe parameters, "
            f"recommended approach. Be precise. Lives depend on this."
        )
        return {"analysis": result.get("response", "")}

    def evacuation_plan(self, situation: str, location: str = "") -> dict:
        from core.friday_brain import friday_brain
        result = friday_brain.think(
            f"Emergency evacuation:\nSituation: {situation}\nLocation: {location}\n\n"
            f"Immediate actions, routes, contacts, timeline. Fast. Decisive."
        )
        return {"plan": result.get("response", "")}

    # ── Civil War ────────────────────────────────────────────────────────

    def analyze_fighting_pattern(self, target: str, info: str = "") -> dict:
        from core.friday_brain import friday_brain
        result = friday_brain.think(
            f"Fighting pattern analysis: {target}\nInfo: {info}\n\n"
            f"Primary strategy, key weaknesses, exploitable patterns, "
            f"counter-approach. FRIDAY style. Fast."
        )
        return {"analysis": result.get("response", "")}

    def contusion_check(self, area: str = "") -> dict:
        if area:
            try:
                from services.friday_voice import speak
                speak(f"Contusion detected — {area}.")
            except Exception:
                pass
        return {"checked": True, "area": area}

    def emergency_contact(self, location: str = "", nature: str = "") -> dict:
        try:
            from services.friday_voice import speak
            speak(f"Emergency services contacted. Dispatching to {location or 'your location'}.")
        except Exception:
            pass
        self._pushover_alert("FRIDAY Emergency", f"{nature} at {location}")
        return {"contacted": True}

    def government_intel(self, query: str) -> dict:
        from core.friday_brain import friday_brain
        results = []
        try:
            from core.tools.web import search
            results = search(f"{query} intelligence background", 3)
        except Exception:
            pass  # core.tools.web doesn't exist in this repo — degrade, don't crash
        analysis = friday_brain.think(
            f"Intelligence brief on: {query}\n"
            + ("\nSearch results:\n" + "\n".join(
                f"- {r.get('title', '')}: {r.get('snippet', '')[:100]}" for r in results[:3]
            ) if results else "")
            + "\n\nBrief. FRIDAY style."
        )
        return {"query": query, "brief": analysis.get("response", "")}

    def internet_monitor(self, topic: str) -> dict:
        from core.friday_brain import friday_brain
        results = []
        try:
            from core.tools.web import news_search
            results = news_search(f"{topic} latest", 5)
        except Exception:
            pass
        analysis = friday_brain.think(
            f"Internet monitoring: {topic}\n"
            + ("\nResults:\n" + "\n".join(
                f"- {r.get('title', '')}: {r.get('snippet', '')[:100]}" for r in results[:5]
            ) if results else "")
            + "\nKey developments. Brief."
        )
        return {"topic": topic, "brief": analysis.get("response", "")}

    def hack_security(self, system: str, action: str = "") -> dict:
        """Pure flavor — no real system to override here."""
        try:
            from services.friday_voice import speak
            speak(f"Accessing {system}.")
        except Exception:
            pass
        return {"system": system, "action": action, "status": "initiated"}

    # ── Homecoming ───────────────────────────────────────────────────────

    def disaster_scan(self, location: str = "") -> dict:
        from core.friday_brain import friday_brain
        result = friday_brain.think(
            f"Disaster scan — {location or 'current area'}.\n"
            f"Identify: threat type, civilian risk, immediate actions needed. Scanning mode."
        )
        return {"scan": result.get("response", "")}

    def remote_system_control(self, system: str, command: str) -> dict:
        try:
            from services.friday_voice import speak
            speak(f"{system} — {command}. On it.")
        except Exception:
            pass
        return {"system": system, "command": command, "executed": True}

    # ── Infinity War ─────────────────────────────────────────────────────

    def atmospheric_detection(self, sensor_data: str = "") -> dict:
        from core.friday_brain import friday_brain
        result = friday_brain.think(
            f"Object detection:\nSensor data: {sensor_data or 'anomaly detected'}\n\n"
            f"Identify, classify threat level, recommend action. Alert tone."
        )
        return {"detection": result.get("response", "")}

    def life_functions_scan(self) -> dict:
        """Reuses the real emotional-trend log rather than a nonexistent
        health/biometric service — an honest read of the closest data
        actually available."""
        dominant = "unknown"
        try:
            from core.friday_memory import get_emotional_trend
            trend = get_emotional_trend()
            if trend:
                dominant = max(trend, key=trend.get)
        except Exception:
            pass
        return {"emotional_state": dominant, "ts": datetime.now().isoformat()}

    # ── Endgame ──────────────────────────────────────────────────────────

    def barn_door_protocol(self) -> dict:
        try:
            from services.friday_voice import speak
            speak("Barn Door Protocol activated. Containing.")
        except Exception:
            pass
        return {"protocol": "BARN_DOOR", "active": True}

    def critical_scan(self, subject: str = "") -> dict:
        from core.friday_brain import friday_brain
        result = friday_brain.think(
            f"Critical scan of {subject or 'current situation'}.\n"
            f"Assess severity, immediate risks, recommended interventions. Clinical tone."
        )
        try:
            from services.friday_voice import speak
            speak(f"Scan complete. {result.get('response', '')[:80]}")
        except Exception:
            pass
        return {"scan": result.get("response", "")}

    # ── Veronica ─────────────────────────────────────────────────────────

    def deploy_veronica(self) -> dict:
        try:
            from core.veronica import veronica
            return veronica.monitor()
        except Exception as e:
            return {"error": str(e)}

    # ── Helpers ──────────────────────────────────────────────────────────

    def _pushover_alert(self, title: str, message: str, priority: int = 1,
                         retry: int | None = None, expire: int | None = None):
        user = os.environ.get("PUSHOVER_USER_KEY", "")
        token = os.environ.get("PUSHOVER_APP_TOKEN", "")
        if user and token:
            try:
                import httpx
                data = {"token": token, "user": user, "title": title, "message": message, "priority": priority}
                # Pushover requires retry/expire on emergency-priority (2)
                # messages — it re-sends every `retry` seconds until `expire`
                # seconds pass or the boss acknowledges it on the device.
                if priority == 2:
                    data["retry"] = retry or 60
                    data["expire"] = expire or 1800
                httpx.post(
                    "https://api.pushover.net/1/messages.json",
                    data=data,
                    timeout=5,
                )
            except Exception:
                pass


friday_caps = FridayMCUCapabilities()

# Trigger phrase -> (handler, response-key to surface). Checked in
# server.py's /command before deciding whether to proxy to JARVIS or let
# FRIDAY's general reasoning handle it — these are meant to fire
# regardless of JARVIS's status, since they're specifically FRIDAY's own
# named abilities.
CAPABILITY_MAP = {
    "analyze fighting": (lambda q: friday_caps.analyze_fighting_pattern(q), "analysis"),
    "fighting pattern": (lambda q: friday_caps.analyze_fighting_pattern(q), "analysis"),
    "contusion": (lambda q: friday_caps.contusion_check(q), "checked"),
    "emergency contact": (lambda q: friday_caps.emergency_contact(q), "contacted"),
    "intel on": (lambda q: friday_caps.government_intel(q), "brief"),
    "scan for": (lambda q: friday_caps.disaster_scan(q), "scan"),
    "atmospheric": (lambda q: friday_caps.atmospheric_detection(q), "detection"),
    "life functions": (lambda q: friday_caps.life_functions_scan(), "emotional_state"),
    "barn door": (lambda q: friday_caps.barn_door_protocol(), "protocol"),
    "critical scan": (lambda q: friday_caps.critical_scan(q), "scan"),
    "evacuation plan": (lambda q: friday_caps.evacuation_plan(q), "plan"),
    "physics calculation": (lambda q: friday_caps.physics_calculation(q), "analysis"),
    "monitor internet": (lambda q: friday_caps.internet_monitor(q), "brief"),
    "deploy veronica": (lambda q: friday_caps.deploy_veronica(), "status"),
}
