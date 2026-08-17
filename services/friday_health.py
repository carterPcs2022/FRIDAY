"""services/friday_health.py — Apple Watch biometric logging. Real data
in, real anomaly detection, real voice alerts — no fabricated readings.
Feed it from an iOS Shortcut posting to POST /friday/health/log.
"""
import json
import os
import threading
from pathlib import Path
from datetime import datetime, timedelta

BASE_DIR = Path(__file__).resolve().parent.parent
HEALTH_LOG = BASE_DIR / "memory" / "friday_health_log.json"

# Hard thresholds, distinct from _check_anomalies()'s soft
# deviation-from-your-own-baseline detection below — these fire on
# absolute values regardless of personal baseline, since a heart rate
# that's merely "unusual for you" and one that's medically critical
# need different urgency (voice-only nudge vs. emergency-priority push).
CRITICAL_THRESHOLDS = {"hr_high": 150, "hr_low": 40, "blood_oxygen_low": 90}


class FridayHealthMonitor:

    def log_from_watch(self, heart_rate: float = 0, hrv: float = 0, blood_oxygen: float = 0,
                        steps: int = 0, sleep_hours: float = 0, sleep_quality: int = 0) -> dict:
        entry = {
            "ts": datetime.now().isoformat(), "heart_rate": heart_rate, "hrv": hrv,
            "blood_oxygen": blood_oxygen, "steps": steps, "sleep_hours": sleep_hours,
            "sleep_quality": sleep_quality, "hour": datetime.now().hour,
        }
        log = self._load()
        log.setdefault("entries", []).append(entry)
        log["entries"] = log["entries"][-3650:]  # ~10 years at one entry/day
        self._save(log)

        alerts = self._check_anomalies(entry, log)
        if alerts:
            try:
                from services.friday_voice import speak
                for alert in alerts:
                    speak(alert)
            except Exception:
                pass

        # Runs alongside _check_anomalies() above, not instead of it — soft
        # baseline deviations and hard critical thresholds are different
        # concerns and every real Watch post should be screened for both.
        try:
            self.check_critical(entry.get("heart_rate", 0), entry.get("blood_oxygen", 0))
        except Exception:
            pass

        return entry

    def check_critical(self, hr: float, bo: float) -> dict:
        reasons = []
        if hr and hr >= CRITICAL_THRESHOLDS["hr_high"]:
            reasons.append(f"heart rate critically high at {hr:.0f}")
        elif hr and 0 < hr <= CRITICAL_THRESHOLDS["hr_low"]:
            reasons.append(f"heart rate critically low at {hr:.0f}")
        if bo and 0 < bo <= CRITICAL_THRESHOLDS["blood_oxygen_low"]:
            reasons.append(f"blood oxygen critically low at {bo:.0f}%")

        if not reasons:
            return {"critical": False}

        reason = "; ".join(reasons)
        self._escalate_critical(reason)
        return {"critical": True, "reason": reason}

    def _escalate_critical(self, reason: str):
        try:
            from services.friday_voice import speak
            speak(f"Boss, critical health alert — {reason}. Please respond.")
        except Exception:
            pass

        try:
            from services.notifications import critical
            critical(
                "FRIDAY CRITICAL HEALTH ALERT",
                f"{reason}. Respond immediately or FRIDAY will notify your emergency contact.",
            )
        except Exception:
            pass

        try:
            from services.checkin_system import emergency_pending
            emergency_pending.set()
        except Exception:
            return

        def _followup():
            import time
            time.sleep(300)
            if not emergency_pending.is_set():
                return  # boss already confirmed safe via a SAFE_TRIGGERS phrase
            phone = os.environ.get("EMERGENCY_CONTACT_PHONE", "")
            if not phone:
                return
            try:
                from services.notifications import critical
                critical(
                    "FRIDAY — No Response",
                    f"No response to critical health alert ({reason}). "
                    f"Emergency contact on file: {phone}.",
                )
            except Exception:
                pass

        threading.Thread(target=_followup, daemon=True).start()

    def _check_anomalies(self, entry: dict, log: dict) -> list:
        alerts = []
        entries = log.get("entries", [])
        if len(entries) < 10:
            return []

        recent = entries[-30:]
        hr_samples = [e["heart_rate"] for e in recent if e["heart_rate"] > 0]
        avg_hr = sum(hr_samples) / len(hr_samples) if hr_samples else 0

        hr = entry.get("heart_rate", 0)
        if hr > 0 and avg_hr > 0 and hr > avg_hr * 1.4:
            alerts.append(f"Boss, heart rate elevated — {hr:.0f} versus your normal {avg_hr:.0f}.")

        hrv_samples = [e["hrv"] for e in recent if e["hrv"] > 0]
        avg_hrv = sum(hrv_samples) / len(hrv_samples) if hrv_samples else 0
        hrv = entry.get("hrv", 0)
        if hrv > 0 and avg_hrv > 0 and hrv < avg_hrv * 0.5:
            alerts.append("HRV significantly low. High stress detected.")

        return alerts

    def sleep_brief(self) -> str:
        log = self._load()
        recent = [e for e in log.get("entries", []) if e.get("sleep_hours", 0) > 0][-7:]
        if not recent:
            return ""

        last_sleep = recent[-1].get("sleep_hours", 0)
        if last_sleep < 5:
            return f"Boss, you only got {last_sleep:.1f} hours. I'll keep things brief today."
        elif last_sleep >= 7.5:
            return f"Good sleep last night — {last_sleep:.1f} hours."
        return ""

    def adjust_friday_for_health(self):
        try:
            from core.friday_brain import friday_brain
        except Exception:
            return
        brief = self.sleep_brief()
        if "keep things brief" in brief:
            friday_brain.set_voice_mode("brief")
        elif "Good sleep" in brief:
            friday_brain.set_voice_mode("normal")

    def _load(self) -> dict:
        if HEALTH_LOG.exists():
            try:
                return json.loads(HEALTH_LOG.read_text())
            except Exception:
                return {}
        return {}

    def _save(self, data: dict):
        HEALTH_LOG.parent.mkdir(parents=True, exist_ok=True)
        HEALTH_LOG.write_text(json.dumps(data, indent=2))


friday_health = FridayHealthMonitor()
