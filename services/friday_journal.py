"""services/friday_journal.py — daily journal entries with a weekly
reflection over them.

Turso is the source of truth (Render's disk is ephemeral — see
db/turso_client.py's module docstring). Cache is hydrated from Turso
once at process start, then kept in sync write-through: every
log_entry() updates the in-memory cache AND Turso immediately. The old
local-JSON path stays as a fallback for both hydrate and write. The old
365-entry cap only bounded the local JSON file's size; list_insert has
no equivalent, so writes also call list_trim (same approach already
applied to notes)."""
import json
from pathlib import Path
from datetime import datetime

from db import turso_client

JOURNAL_FILE = Path("memory/friday_journal.json")
JOURNAL_TABLE = "journal"
_JOURNAL_CAP = 365


class FridayJournal:

    def __init__(self):
        self._entries = self._hydrate()

    def log_entry(self, content: str, mood: str = "neutral") -> dict:
        entry = {
            "date": datetime.now().date().isoformat(),
            "ts": datetime.now().isoformat(),
            "content": content, "mood": mood,
            "hour": datetime.now().hour,
        }
        self._write_through(entry)  # may attach a Turso-assigned "id" to `entry` in place
        self._entries.append(entry)
        self._entries = self._entries[-_JOURNAL_CAP:]
        return {"logged": True, "entry": entry}

    def recent_entries(self, days: int = 7) -> list:
        """Public accessor — used by core/autonomous_agent.py's weekly
        review instead of reaching into _load() directly."""
        return [
            e for e in self._entries
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

    # ── Turso (source of truth) with local-JSON fallback ────────────────────

    def _hydrate(self) -> list:
        if turso_client.is_configured():
            try:
                return turso_client.list_all(JOURNAL_TABLE)
            except Exception as e:
                print(f"[FRIDAY] Turso hydrate failed for journal, falling back to local JSON: {e}")
        return self._load_local()

    def _write_through(self, entry: dict):
        if turso_client.is_configured():
            try:
                entry["id"] = turso_client.list_insert(JOURNAL_TABLE, entry)
            except Exception as e:
                print(f"[FRIDAY] Turso write failed for journal, falling back to local JSON: {e}")
                self._save_local(self._entries + [entry])
                return
            try:
                turso_client.list_trim(JOURNAL_TABLE, _JOURNAL_CAP)
            except Exception as e:
                print(f"[FRIDAY] Turso trim failed for journal (non-fatal): {e}")
            return
        self._save_local(self._entries + [entry])

    def _load_local(self) -> list:
        if JOURNAL_FILE.exists():
            try:
                return json.loads(JOURNAL_FILE.read_text())
            except Exception:
                return []
        return []

    def _save_local(self, data: list):
        JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
        JOURNAL_FILE.write_text(json.dumps(data, indent=2))


journal = FridayJournal()
