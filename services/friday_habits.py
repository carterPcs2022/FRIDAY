"""services/friday_habits.py — daily habit logging with streak tracking.

Turso is the source of truth (Render's disk is ephemeral — see
db/turso_client.py's module docstring). Cache is hydrated from Turso
once at process start, then kept in sync write-through: every log()
updates the in-memory cache AND Turso immediately, so reads stay fast
(no network hop) while nothing is ever lost to a redeploy. The old
local-JSON path stays as a fallback for both hydrate and write — if
Turso is unconfigured or a call fails, this falls back to it rather
than hard-crashing habit logging. Remove the fallback once Turso's
been stable for a few days (tracked alongside the other 8 files)."""
import json
from pathlib import Path
from datetime import datetime, timedelta

from db import turso_client

HABITS_FILE = Path("memory/friday_habits.json")
TURSO_TABLE = "habits"


class HabitTracker:

    def __init__(self):
        self._data = self._hydrate()

    def log(self, habit: str) -> dict:
        self._data.setdefault(habit, []).append(datetime.now().date().isoformat())
        self._data[habit] = sorted(set(self._data[habit]))[-365:]
        self._write_through(habit)
        return {"habit": habit, "streak": self.streak(habit), "logged": True}

    def streak(self, habit: str) -> int:
        dates = sorted(self._data.get(habit, []), reverse=True)
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
        return {h: self.streak(h) for h in self._data}

    # ── Turso (source of truth) with local-JSON fallback ────────────────────

    def _hydrate(self) -> dict:
        """Startup always tries to load what's actually there in Turso —
        never assumes the cache starts empty. Only falls back to the
        local file if Turso isn't configured or the read fails."""
        if turso_client.is_configured():
            try:
                return turso_client.kv_all(TURSO_TABLE)
            except Exception as e:
                print(f"[FRIDAY] Turso hydrate failed for habits, falling back to local JSON: {e}")
        return self._load_local()

    def _write_through(self, habit: str):
        if turso_client.is_configured():
            try:
                turso_client.kv_set(TURSO_TABLE, habit, self._data[habit])
                return
            except Exception as e:
                print(f"[FRIDAY] Turso write failed for habits, falling back to local JSON: {e}")
        self._save_local(self._data)

    def _load_local(self) -> dict:
        if HABITS_FILE.exists():
            try:
                return json.loads(HABITS_FILE.read_text())
            except Exception:
                return {}
        return {}

    def _save_local(self, data: dict):
        HABITS_FILE.parent.mkdir(parents=True, exist_ok=True)
        HABITS_FILE.write_text(json.dumps(data, indent=2))


habits = HabitTracker()
