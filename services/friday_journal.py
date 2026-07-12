"""services/friday_journal.py — daily journal entries with a weekly
reflection over them."""
import json
from pathlib import Path
from datetime import datetime

JOURNAL_FILE = Path("memory/friday_journal.json")


class FridayJournal:

    def log_entry(self, content: str, mood: str = "neutral") -> dict:
        entries = self._load()
        entry = {
            "date": datetime.now().date().isoformat(),
            "ts": datetime.now().isoformat(),
            "content": content, "mood": mood,
            "hour": datetime.now().hour,
        }
        entries.append(entry)
        entries = entries[-365:]
        self._save(entries)
        return {"logged": True, "entry": entry}

    def recent_entries(self, days: int = 7) -> list:
        """Public accessor — used by core/autonomous_agent.py's weekly
        review instead of reaching into _load() directly."""
        entries = self._load()
        return [
            e for e in entries
            if (datetime.now() - datetime.fromisoformat(e["ts"])).days < days
        ]

    def weekly_reflection(self) -> str:
        this_week = self.recent_entries(7)
        if not this_week:
            return "No journal entries this week yet, boss."

        from core.friday_brain import friday_brain
        result = friday_brain.think(
            f"Weekly journal reflection:\n\n"
            + "\n".join(f"{e['date']}: {e['content'][:100]}" for e in this_week)
            + "\n\nReflect on this week's patterns. What's been on your mind? "
              "Under 60 words. Warm. FRIDAY style."
        )
        return result["response"]

    def _load(self) -> list:
        if JOURNAL_FILE.exists():
            try:
                return json.loads(JOURNAL_FILE.read_text())
            except Exception:
                return []
        return []

    def _save(self, data: list):
        JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
        JOURNAL_FILE.write_text(json.dumps(data, indent=2))


journal = FridayJournal()
