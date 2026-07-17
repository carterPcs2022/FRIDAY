"""services/friday_journal.py — daily journal entries with a weekly
reflection over them. Turso is the read source of truth (list_* table);
local JSON stays a write-through cache and fallback, matching
core/friday_bills.py."""
import json
from pathlib import Path
from datetime import datetime

from db import turso_http_client as turso

JOURNAL_FILE = Path("memory/friday_journal.json")
JOURNAL_TABLE = "journal"


class FridayJournal:

    def log_entry(self, content: str, mood: str = "neutral") -> dict:
        entries = self._read_local()
        entry = {
            "date": datetime.now().date().isoformat(),
            "ts": datetime.now().isoformat(),
            "content": content, "mood": mood,
            "hour": datetime.now().hour,
        }
        entries.append(entry)
        entries = entries[-365:]
        self._write_local(entries)

        if turso.is_configured():
            try:
                turso.ensure_list_table(JOURNAL_TABLE)
                turso.list_insert(JOURNAL_TABLE, entry)
            except Exception as e:
                print(f"[Turso] journal write failed, local JSON already has it: {e}")

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
        if turso.is_configured():
            rows = None
            try:
                turso.ensure_list_table(JOURNAL_TABLE)
                rows = turso.list_all(JOURNAL_TABLE)
            except Exception as e:
                print(f"[Turso] journal read failed, falling back to local JSON: {e}")
            if rows:
                return rows
            if rows is not None:
                local = self._read_local()
                for record in local:
                    try:
                        turso.list_insert(JOURNAL_TABLE, record)
                    except Exception as e:
                        print(f"[Turso] journal seed failed: {e}")
                return local
        return self._read_local()

    def _read_local(self) -> list:
        if JOURNAL_FILE.exists():
            try:
                return json.loads(JOURNAL_FILE.read_text())
            except Exception:
                return []
        return []

    def _write_local(self, data: list):
        JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
        JOURNAL_FILE.write_text(json.dumps(data, indent=2))


journal = FridayJournal()
