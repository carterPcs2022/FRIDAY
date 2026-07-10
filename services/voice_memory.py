"""services/voice_memory.py — tracks emotional/urgency patterns by hour
of day, and suggests the voice mode that's fit best at this hour
historically."""
import json
from pathlib import Path
from datetime import datetime
from collections import Counter

VOICE_PROFILE_FILE = Path("memory/voice_profile.json")


class VoiceMemory:

    def __init__(self):
        self._profile = self._load()

    def analyze_and_learn(self, transcript: str) -> dict:
        from core.emotional_intel import emotional_intel

        emotion = emotional_intel.analyze(transcript)
        hour = datetime.now().hour
        urgency = any(w in transcript.lower() for w in
                     ["now", "urgent", "quick", "help", "emergency"])

        self._profile.setdefault("sessions", []).append({
            "ts": datetime.now().isoformat(), "hour": hour,
            "emotion": emotion.get("emotion", "neutral"),
            "intensity": emotion.get("intensity", 0), "urgency": urgency,
        })
        self._profile["sessions"] = self._profile["sessions"][-500:]

        key = str(hour)
        self._profile.setdefault("hourly_patterns", {}).setdefault(key, []).append(
            emotion.get("emotion", "neutral"))
        self._profile["hourly_patterns"][key] = self._profile["hourly_patterns"][key][-30:]

        self._save()
        return {"emotion": emotion.get("emotion", "neutral"), "urgency": urgency}

    def get_current_best_mode(self) -> str:
        """Only ever returns a real FRIDAY_VOICE_MODES key (normal/
        focused/support) — never coverage, since that mode is meant to be
        set only by actual JARVIS-down coverage logic, not an hourly-
        pattern guess."""
        hour = datetime.now().hour
        patterns = self._profile.get("hourly_patterns", {}).get(str(hour), [])
        if not patterns:
            return "normal"
        dominant = Counter(patterns).most_common(1)[0][0]
        return {
            "stressed": "focused", "tired": "support",
            "sad": "support", "frustrated": "focused",
        }.get(dominant, "normal")

    def weekly_report(self) -> str:
        from core.friday_brain import friday_brain

        sessions = self._profile.get("sessions", [])[-50:]
        if not sessions:
            return ""
        emotions = Counter(s.get("emotion", "neutral") for s in sessions)
        result = friday_brain.think(
            f"Weekly emotional summary: {dict(emotions)}\n\n"
            f"Brief insight. Supportive. Under 25 words."
        )
        return result["response"]

    def predict_energy_now(self) -> str:
        """One-sentence read on current energy based on the last few
        hours' logged emotional patterns."""
        hour = datetime.now().hour
        patterns = self._profile.get("hourly_patterns", {})

        hour_data = []
        for h in range(max(0, hour - 3), hour + 1):
            emotions = patterns.get(str(h), [])
            if emotions:
                dominant = Counter(emotions).most_common(1)[0][0]
                hour_data.append(f"{h}:00 — {dominant}")

        if not hour_data:
            return ""

        from core.friday_brain import friday_brain
        result = friday_brain.think(
            f"Energy pattern right now:\n"
            + "\n".join(hour_data)
            + f"\n\nCurrent time: {hour}:00\n\n"
              f"One sentence energy prediction. Should boss do deep work, "
              f"admin, or rest? Under 15 words."
        )
        return result["response"]

    def _load(self) -> dict:
        if VOICE_PROFILE_FILE.exists():
            try:
                return json.loads(VOICE_PROFILE_FILE.read_text())
            except Exception:
                return {}
        return {}

    def _save(self):
        VOICE_PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
        VOICE_PROFILE_FILE.write_text(json.dumps(self._profile, indent=2))


voice_memory = VoiceMemory()
