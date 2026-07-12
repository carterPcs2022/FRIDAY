"""
Medicine schedule tracking and reminders.
Pure scheduling tool — stores what the user tells it,
reminds at the times the user specifies. No medical
judgment or advice logic anywhere in this module.
"""

import json, time
from pathlib import Path
from datetime import datetime

MEDICINE_FILE = Path("memory/friday_medicine.json")

class MedicineTracker:

    def add_medicine(self, name: str,
                      times: list,
                      dosage: str = "",
                      notes: str = "") -> dict:
        """
        Add a medicine to track.
        times: list of "HH:MM" strings, e.g. ["08:00","20:00"]
        """
        meds = self._load()
        med_id = f"med_{int(time.time())}"
        meds[med_id] = {
            "id": med_id,
            "name": name,
            "dosage": dosage,
            "times": times,
            "notes": notes,
            "active": True,
            "created": datetime.now().isoformat(),
            "log": [],
        }
        self._save(meds)
        return {"added": True, "id": med_id, "name": name}

    def remove_medicine(self, name: str) -> dict:
        meds = self._load()
        for med_id, med in list(meds.items()):
            if med["name"].lower() == name.lower():
                meds[med_id]["active"] = False
                self._save(meds)
                return {"removed": True, "name": name}
        return {"removed": False, "error": "Not found"}

    def get_active_medicines(self) -> list:
        meds = self._load()
        return [m for m in meds.values() if m.get("active")]

    def log_taken(self, name: str) -> dict:
        """Mark a dose as taken right now."""
        meds = self._load()
        for med_id, med in meds.items():
            if med["name"].lower() == name.lower():
                med.setdefault("log", []).append({
                    "ts": datetime.now().isoformat(),
                    "action": "taken",
                })
                med["log"] = med["log"][-100:]
                self._save(meds)
                return {"logged": True, "name": name}
        return {"logged": False, "error": "Not found"}

    def log_skipped(self, name: str, reason: str = "") -> dict:
        meds = self._load()
        for med_id, med in meds.items():
            if med["name"].lower() == name.lower():
                med.setdefault("log", []).append({
                    "ts": datetime.now().isoformat(),
                    "action": "skipped",
                    "reason": reason,
                })
                med["log"] = med["log"][-100:]
                self._save(meds)
                return {"logged": True, "name": name}
        return {"logged": False, "error": "Not found"}

    def get_due_now(self, window_minutes: int = 5) -> list:
        """
        Check which medicines are due right now
        (within window_minutes of a scheduled time).
        """
        meds = self.get_active_medicines()
        now = datetime.now()
        due = []

        for med in meds:
            for time_str in med.get("times", []):
                try:
                    hour, minute = map(int, time_str.split(":"))
                    scheduled = now.replace(
                        hour=hour, minute=minute,
                        second=0, microsecond=0
                    )
                    diff_minutes = abs(
                        (now - scheduled).total_seconds() / 60
                    )
                    if diff_minutes <= window_minutes:
                        # Check if already logged as taken
                        # today for this time slot
                        already_taken = any(
                            log["action"] == "taken" and
                            log["ts"][:10] == now.date().isoformat()
                            for log in med.get("log", [])
                        )
                        if not already_taken:
                            due.append({
                                "name": med["name"],
                                "dosage": med.get("dosage",""),
                                "scheduled_time": time_str,
                            })
                except Exception:
                    pass
        return due

    def get_missed_today(self) -> list:
        """
        Check for doses scheduled earlier today that
        were never logged as taken (more than 2 hours late).
        """
        meds = self.get_active_medicines()
        now = datetime.now()
        missed = []

        for med in meds:
            for time_str in med.get("times", []):
                try:
                    hour, minute = map(int, time_str.split(":"))
                    scheduled = now.replace(
                        hour=hour, minute=minute,
                        second=0, microsecond=0
                    )
                    if scheduled > now:
                        continue  # Not due yet today
                    minutes_late = (
                        now - scheduled
                    ).total_seconds() / 60
                    if minutes_late > 120:  # 2+ hours late
                        already_taken = any(
                            log["action"] == "taken" and
                            log["ts"][:10] == now.date().isoformat()
                            for log in med.get("log", [])
                        )
                        if not already_taken:
                            missed.append({
                                "name": med["name"],
                                "scheduled_time": time_str,
                                "minutes_late": int(minutes_late),
                            })
                except Exception:
                    pass
        return missed

    def get_schedule_summary(self) -> str:
        """Human-readable summary of today's schedule."""
        meds = self.get_active_medicines()
        if not meds:
            return "No medicines currently tracked, boss."

        lines = []
        for med in meds:
            times_str = ", ".join(med.get("times", []))
            dosage = f" ({med['dosage']})" if med.get("dosage") else ""
            lines.append(f"{med['name']}{dosage} at {times_str}")
        return "; ".join(lines)

    def _load(self) -> dict:
        if MEDICINE_FILE.exists():
            with open(MEDICINE_FILE) as f:
                try: return json.load(f)
                except Exception: return {}
        return {}

    def _save(self, data: dict):
        MEDICINE_FILE.parent.mkdir(exist_ok=True)
        with open(MEDICINE_FILE, "w") as f:
            json.dump(data, f, indent=2)


medicine_tracker = MedicineTracker()
