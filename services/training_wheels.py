"""services/training_wheels.py — earned autonomy for FRIDAY's more
consequential actions. New capabilities start locked at a low trust
score; each real outcome (success or failure) nudges the score up or
down, and crossing a tier boundary unlocks that tier's actions — same
"earn it, don't assume it" spirit as JARVIS's range protocols, but
scoped to a single 0-100 number rather than a full state machine.
"""
import json
from pathlib import Path

TRUST_FILE = Path("memory/training_wheels.json")

# Action -> tier it requires. Only "mac_bridge_control" is actually wired
# to a real handler in this repo today (the HOMEKIT_TRIGGERS dispatch in
# server.py) — the rest are named ahead of features that don't exist yet
# here (no real outbound email-send or call-initiate action in this repo),
# left in so can_perform()/status() have a stable shape once those land.
POWER_TIERS = {
    "tier_1": {"trust_required": 0,  "actions": ["read_status", "log_health", "log_habit", "journal", "task_manage"]},
    "tier_2": {"trust_required": 30, "actions": ["homekit_control", "calendar_write", "reminder_set"]},
    "tier_3": {"trust_required": 60, "actions": ["email_send", "mac_bridge_control"]},
    "tier_4": {"trust_required": 90, "actions": ["call_initiate", "financial_action"]},
}


class TrainingWheels:

    def __init__(self):
        self._data = self._load()

    def _load(self) -> dict:
        if TRUST_FILE.exists():
            try:
                return json.loads(TRUST_FILE.read_text())
            except Exception:
                return {"trust": 20}
        return {"trust": 20}

    def _save(self):
        TRUST_FILE.parent.mkdir(parents=True, exist_ok=True)
        TRUST_FILE.write_text(json.dumps(self._data, indent=2))

    def _tier_for_action(self, action: str):
        for tier, info in POWER_TIERS.items():
            if action in info["actions"]:
                return tier, info["trust_required"]
        return None

    def _current_tier(self, trust: int) -> str:
        unlocked = "tier_1"
        for tier, info in sorted(POWER_TIERS.items(), key=lambda kv: kv[1]["trust_required"]):
            if trust >= info["trust_required"]:
                unlocked = tier
        return unlocked

    def can_perform(self, action: str) -> bool:
        """Actions not listed in POWER_TIERS aren't gated by this system at
        all — training wheels only apply to the specific actions wired to
        call it, not a default-deny over everything FRIDAY does."""
        match = self._tier_for_action(action)
        if not match:
            return True
        _, required = match
        return self._data.get("trust", 20) >= required

    def record_outcome(self, action: str, success: bool, notes: str = ""):
        trust = self._data.get("trust", 20)
        before_tier = self._current_tier(trust)

        trust = max(0, min(100, trust + (2 if success else -5)))
        self._data["trust"] = trust
        self._data.setdefault("history", []).append({
            "action": action, "success": success, "notes": notes, "trust": trust,
        })
        self._data["history"] = self._data["history"][-200:]
        self._save()

        after_tier = self._current_tier(trust)
        if POWER_TIERS[after_tier]["trust_required"] > POWER_TIERS[before_tier]["trust_required"]:
            try:
                from services.friday_voice import speak
                speak(f"Trust threshold reached, boss. {after_tier.replace('_', ' ').title()} unlocked.")
            except Exception:
                pass

    def status(self) -> dict:
        trust = self._data.get("trust", 20)
        return {"trust": trust, "tier": self._current_tier(trust), "tiers": POWER_TIERS}


training_wheels = TrainingWheels()
