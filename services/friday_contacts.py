"""services/friday_contacts.py — lightweight personal CRM. Civil War's
red/green enemy-ally coding, as a simple relationship tag + color per
contact you manually add."""
import json
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent
CONTACTS_FILE = BASE_DIR / "memory" / "friday_contacts.json"

RELATIONSHIP_COLORS = {
    "ally": "#00ff80", "neutral": "#00b4ff", "unknown": "#ffaa00",
    "threat": "#ff4444", "client": "#00ffcc", "friend": "#00ff80",
}


class FridayContacts:

    def add_contact(self, name: str, relationship: str = "neutral", notes: str = "",
                     email: str = "", phone: str = "") -> dict:
        contacts = self._load()
        existing = contacts.get(name, {})
        contacts[name] = {
            "name": name, "relationship": relationship,
            "color": RELATIONSHIP_COLORS.get(relationship, "#ffaa00"),
            "notes": notes,
            # Re-adding a known contact (e.g. to set their email later)
            # shouldn't blank out an address that was set separately —
            # only overwrite when the caller actually passed a new one.
            "email": email or existing.get("email", ""),
            "phone": phone or existing.get("phone", ""),
            "added": existing.get("added") or datetime.now().isoformat(),
            "last_seen": existing.get("last_seen"),
        }
        self._save(contacts)
        return contacts[name]

    def find_by_name(self, query: str) -> dict:
        """Resolves a name/nickname to a stored contact — exact key match
        first, then substring, so "email pepper" finds a contact stored
        as "Pepper Potts". Returns {} if nothing matches, same shape as a
        miss in every other lookup here (find_email, get_intel)."""
        if not query:
            return {}
        contacts = self._load()
        if query in contacts:
            return contacts[query]
        q_low = query.lower()
        for name, contact in contacts.items():
            if q_low in name.lower():
                return contact
        return {}

    def get_intel(self, name: str) -> dict:
        """Quick, grounded brief — only reasons over what's actually
        stored for this contact, not a fabricated background check."""
        contacts = self._load()
        contact = contacts.get(name, {})
        if not contact:
            return {"unknown": True, "name": name}

        try:
            from core.friday_brain import friday_brain
            result = friday_brain.think(
                f"Quick note on {name}: relationship is '{contact.get('relationship', '')}', "
                f"notes: '{contact.get('notes', '')}'. One brief, practical reminder for "
                f"interacting with them right now. Under 30 words."
            )
            brief = result.get("response", "")
        except Exception:
            brief = ""

        return {**contact, "brief": brief}

    def get_all(self) -> dict:
        return self._load()

    def _load(self) -> dict:
        if CONTACTS_FILE.exists():
            try:
                return json.loads(CONTACTS_FILE.read_text())
            except Exception:
                return {}
        return {}

    def _save(self, data: dict):
        CONTACTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONTACTS_FILE.write_text(json.dumps(data, indent=2))


friday_contacts = FridayContacts()
