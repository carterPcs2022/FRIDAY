"""services/friday_continuity.py — FRIDAY remembers not just facts but
feelings. If you were stressed last night she checks in this morning
without being asked."""
import json
from pathlib import Path
from datetime import datetime, timedelta

CONTINUITY_FILE = Path("memory/friday_continuity.json")

FOLLOWUP_EMOTIONS = [
    "stressed", "anxious", "sad", "frustrated",
    "worried", "overwhelmed", "angry", "upset",
]


class EmotionalContinuity:

    def __init__(self):
        self._state = self._load()

    def record_session(self, emotion: str, intensity: int, context: str = "", topic: str = "") -> dict:
        entry = {
            "ts": datetime.now().isoformat(),
            "emotion": emotion, "intensity": intensity,
            "context": context[:200], "topic": topic[:100],
            "date": datetime.now().date().isoformat(),
            "hour": datetime.now().hour,
            "followed_up": False,
        }
        self._state.setdefault("sessions", []).append(entry)
        self._state["sessions"] = self._state["sessions"][-200:]
        self._save()
        return entry

    def get_pending_followups(self) -> list:
        """High-intensity negative emotions from yesterday or today that
        haven't been checked in on yet."""
        now = datetime.now()
        yesterday = (now - timedelta(days=1)).date().isoformat()
        today = now.date().isoformat()

        sessions = self._state.get("sessions", [])
        pending = []
        for s in sessions:
            if s.get("date", "") not in (yesterday, today):
                continue
            if (s.get("emotion", "") in FOLLOWUP_EMOTIONS
                    and s.get("intensity", 0) >= 5
                    and not s.get("followed_up", False)):
                pending.append(s)
        return pending

    def generate_followup(self) -> str:
        pending = self.get_pending_followups()
        if not pending:
            return ""

        most_recent = pending[-1]
        emotion = most_recent.get("emotion", "")
        context = most_recent.get("context", "")
        topic = most_recent.get("topic", "")
        hour = most_recent.get("hour", 12)

        time_ref = ("last night" if hour >= 18 else
                    "earlier today" if hour >= 12 else "this morning")

        from core.friday_brain import friday_brain
        result = friday_brain.think(
            f"FRIDAY following up on emotional state:\n"
            f"User was {emotion} (intensity {most_recent['intensity']}/10) {time_ref}.\n"
            f"Context: {context}\nTopic: {topic}\n\n"
            f"Generate a warm natural follow-up check-in.\n"
            f"NOT 'I noticed you were stressed' — more natural.\n"
            f"Like a friend checking in, not an AI logging data.\n"
            f"Under 20 words. FRIDAY style."
        )

        most_recent["followed_up"] = True
        self._save()

        return result["response"]

    def morning_emotional_check(self) -> str:
        followup = self.generate_followup()
        if followup:
            try:
                from services.friday_voice import speak
                speak(followup)
            except Exception:
                pass
        return followup

    def record_topic(self, topic: str, resolved: bool = False):
        topics = self._state.setdefault("topics", {})
        if topic not in topics:
            topics[topic] = {
                "first_mentioned": datetime.now().isoformat(),
                "mentions": 0, "resolved": False, "last_emotion": "neutral",
            }
        topics[topic]["mentions"] += 1
        topics[topic]["last_mentioned"] = datetime.now().isoformat()
        if resolved:
            topics[topic]["resolved"] = True
        self._save()

    def get_unresolved_topics(self) -> list:
        topics = self._state.get("topics", {})
        return [
            {"topic": k, **v} for k, v in topics.items()
            if not v.get("resolved") and v.get("mentions", 0) >= 2
        ]

    def _load(self) -> dict:
        if CONTINUITY_FILE.exists():
            try:
                return json.loads(CONTINUITY_FILE.read_text())
            except Exception:
                return {}
        return {}

    def _save(self):
        CONTINUITY_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONTINUITY_FILE.write_text(json.dumps(self._state, indent=2))

    def status(self) -> dict:
        return {
            "sessions": len(self._state.get("sessions", [])),
            "pending_followups": len(self.get_pending_followups()),
            "tracked_topics": len(self._state.get("topics", {})),
            "unresolved": len(self.get_unresolved_topics()),
        }


continuity = EmotionalContinuity()
