"""services/friday_relationships.py — tracks who you've talked to and
when, and flags people you haven't been in touch with."""
import json
from pathlib import Path
from datetime import datetime


PEOPLE_FILE = Path("memory/friday_people.json")


class RelationshipIntel:

    def __init__(self):
        self._people = self._load()

    def log_contact(self, name: str, notes: str = "") -> dict:
        if name not in self._people:
            self._people[name] = {"name": name, "contacts": [], "notes": []}
        self._people[name]["contacts"].append({
            "ts": datetime.now().isoformat(), "notes": notes
        })
        self._people[name]["last_contact"] = datetime.now().isoformat()
        if notes:
            self._people[name]["notes"].append(notes)
            self._people[name]["notes"] = self._people[name]["notes"][-20:]
        self._save()
        return {"logged": True, "person": name}

    def get_intel(self, name: str) -> dict:
        from core.friday_brain import friday_brain

        person = self._people.get(name)
        if not person:
            return {"unknown": True, "name": name}

        last = person.get("last_contact", "")
        days = 0
        if last:
            try:
                days = (datetime.now() - datetime.fromisoformat(last)).days
            except Exception:
                pass

        notes = "\n".join(person.get("notes", [])[-3:])
        brief = friday_brain.think(
            f"Intel brief on {name}:\nLast contact: {days} days ago\nNotes: {notes}\n\nUnder 20 words."
        )
        return {**person, "days_since": days, "brief": brief["response"]}

    def who_needs_attention(self) -> list:
        overdue = []
        now = datetime.now()
        for name, person in self._people.items():
            last = person.get("last_contact", "")
            if not last:
                continue
            try:
                days = (now - datetime.fromisoformat(last)).days
                if days >= 14:
                    overdue.append({"name": name, "days_since": days})
            except Exception:
                pass
        return sorted(overdue, key=lambda x: x["days_since"], reverse=True)

    def relationship_brief(self) -> str:
        overdue = self.who_needs_attention()
        if not overdue:
            return ""
        from core.friday_brain import friday_brain

        result = friday_brain.think(
            f"These people need contact:\n"
            + "\n".join(f"- {p['name']}: {p['days_since']} days" for p in overdue[:3])
            + "\nFriendly reminder. Under 20 words."
        )
        return result["response"]

    def _load(self) -> dict:
        if PEOPLE_FILE.exists():
            try:
                return json.loads(PEOPLE_FILE.read_text())
            except Exception:
                return {}
        return {}

    def _save(self):
        PEOPLE_FILE.parent.mkdir(parents=True, exist_ok=True)
        PEOPLE_FILE.write_text(json.dumps(self._people, indent=2))


relationships = RelationshipIntel()
