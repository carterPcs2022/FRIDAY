"""services/friday_habits.py — daily habit logging with streak tracking.
Turso is the read source of truth (dict keyed by habit name); local JSON
stays a write-through cache and fallback, matching core/friday_bills.py.
"""
import json
from pathlib import Path
from datetime import datetime, timedelta

from db import turso_http_client as turso

HABITS_FILE = Path("memory/friday_habits.json")
HABITS_TABLE = "habits"


class HabitTracker:

    def __init__(self):
        self._habits = self._load()

    def log(self, habit: str) -> dict:
        today = datetime.now().date().isoformat()
        self._habits.setdefault(habit, []).append(today)
        self._habits[habit] = sorted(set(self._habits[habit]))[-365:]
        self._save(habit)
        return {"habit": habit, "streak": self.streak(habit), "logged": True}

    def streak(self, habit: str) -> int:
        dates = sorted(self._habits.get(habit, []), reverse=True)
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
        return {h: self.streak(h) for h in self._habits}

    def _load(self) -> dict:
        if turso.is_configured():
            rows = None
            try:
                turso.ensure_kv_table(HABITS_TABLE)
                rows = turso.kv_all(HABITS_TABLE)
            except Exception as e:
                print(f"[Turso] habits read failed, falling back to local JSON: {e}")
            if rows:
                return rows
            if rows is not None:
                local = self._read_local()
                for habit, dates in local.items():
                    try:
                        turso.kv_set(HABITS_TABLE, habit, dates)
                    except Exception as e:
                        print(f"[Turso] habits seed failed: {e}")
                return local
        return self._read_local()

    def _read_local(self) -> dict:
        if HABITS_FILE.exists():
            try:
                return json.loads(HABITS_FILE.read_text())
            except Exception:
                return {}
        return {}

    def _save(self, habit: str):
        HABITS_FILE.parent.mkdir(parents=True, exist_ok=True)
        HABITS_FILE.write_text(json.dumps(self._habits, indent=2))

        if turso.is_configured():
            try:
                turso.ensure_kv_table(HABITS_TABLE)
                turso.kv_set(HABITS_TABLE, habit, self._habits[habit])
            except Exception as e:
                print(f"[Turso] habits write failed, local JSON already has it: {e}")


habits = HabitTracker()
