"""services/friday_habits.py — daily habit logging with streak tracking."""
import json
from pathlib import Path
from datetime import datetime, timedelta

HABITS_FILE = Path("memory/friday_habits.json")


class HabitTracker:

    def log(self, habit: str) -> dict:
        data = self._load()
        today = datetime.now().date().isoformat()
        data.setdefault(habit, []).append(today)
        data[habit] = sorted(set(data[habit]))[-365:]
        self._save(data)
        return {"habit": habit, "streak": self.streak(habit), "logged": True}

    def streak(self, habit: str) -> int:
        data = self._load()
        dates = sorted(data.get(habit, []), reverse=True)
        if not dates:
            return 0
        streak = 0
        check = datetime.now().date()
        for d in dates:
            date = datetime.fromisoformat(d).date()
            if date >= check - timedelta(days=1):
                streak += 1
                check = date - timedelta(days=1)
            else:
                break
        return streak

    def all_streaks(self) -> dict:
        data = self._load()
        return {h: self.streak(h) for h in data}

    def _load(self) -> dict:
        if HABITS_FILE.exists():
            try:
                return json.loads(HABITS_FILE.read_text())
            except Exception:
                return {}
        return {}

    def _save(self, data: dict):
        HABITS_FILE.parent.mkdir(parents=True, exist_ok=True)
        HABITS_FILE.write_text(json.dumps(data, indent=2))


habits = HabitTracker()
