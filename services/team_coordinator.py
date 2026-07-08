"""services/team_coordinator.py — track status/task/location for people
you're coordinating with. Manually updated, not auto-detected."""
import json
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent
TEAM_FILE = BASE_DIR / "memory" / "team_status.json"


class TeamCoordinator:

    def update_member(self, name: str, status: str, task: str = "", location: str = "") -> dict:
        team = self._load()
        team[name] = {
            "name": name, "status": status, "task": task, "location": location,
            "updated": datetime.now().isoformat(),
        }
        self._save(team)
        return team[name]

    def team_brief(self) -> str:
        team = self._load()
        if not team:
            return "No team members tracked."
        try:
            from core.friday_brain import friday_brain
            result = friday_brain.think(
                "Team status brief:\n"
                + "\n".join(f"- {m['name']}: {m['status']} — {m.get('task', '')}" for m in team.values())
                + "\n\nQuick summary. Who needs attention?"
            )
            return result.get("response", "")
        except Exception:
            return "Brief unavailable right now."

    def get_all(self) -> dict:
        return self._load()

    def _load(self) -> dict:
        if TEAM_FILE.exists():
            try:
                return json.loads(TEAM_FILE.read_text())
            except Exception:
                return {}
        return {}

    def _save(self, data: dict):
        TEAM_FILE.parent.mkdir(parents=True, exist_ok=True)
        TEAM_FILE.write_text(json.dumps(data, indent=2))


team = TeamCoordinator()
