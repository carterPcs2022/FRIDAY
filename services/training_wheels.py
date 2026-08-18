"""services/training_wheels.py — earned autonomy for FRIDAY's more
consequential actions. New capabilities start locked at a low trust
score; each real outcome (success or failure) nudges the score up or
down, and crossing a tier boundary unlocks that tier's actions — same
"earn it, don't assume it" spirit as JARVIS's range protocols, but
scoped to a single 0-100 number rather than a full state machine.

Turso is the read source of truth once configured, local JSON stays a
write-through cache and fallback — same pattern as core/friday_memory.py's
profile (a single object under one fixed key, not a growing list of
records, since trust/history live together as one blob). Wasn't part of
the original migration; a page refresh never touched it (that's browser-
side, not server state), but a Render redeploy wiping local disk did —
trust score and the entire outcome history reset to the default any time
that happened.
"""
import json
from pathlib import Path

from db import turso_http_client as turso

TRUST_FILE = Path("memory/training_wheels.json")
TRUST_TABLE = "training_wheels"
TRUST_KEY = "training_wheels"

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
        if turso.is_configured():
            row, query_ok = None, False
            try:
                turso.ensure_kv_table(TRUST_TABLE)
                row = turso.kv_get(TRUST_TABLE, TRUST_KEY)
                query_ok = True
            except Exception as e:
                print(f"[Turso] training_wheels read failed, falling back to local JSON: {e}")

            if row is not None:
                return row
            if query_ok:
                # Query succeeded but the key doesn't exist yet — first
                # read since migrating, seed Turso from local JSON (or,
                # on a genuinely fresh install with neither, the same
                # {"trust": 20} default local-only mode would start with).
                local = self._read_local()
                try:
                    turso.kv_set(TRUST_TABLE, TRUST_KEY, local)
                except Exception as e:
                    print(f"[Turso] training_wheels seed failed: {e}")
                return local

        return self._read_local()

    def _read_local(self) -> dict:
        if TRUST_FILE.exists():
            try:
                return json.loads(TRUST_FILE.read_text())
            except Exception:
                return {"trust": 20}
        return {"trust": 20}

    def _save(self):
        TRUST_FILE.parent.mkdir(parents=True, exist_ok=True)
        TRUST_FILE.write_text(json.dumps(self._data, indent=2))

        if turso.is_configured():
            try:
                turso.ensure_kv_table(TRUST_TABLE)
                turso.kv_set(TRUST_TABLE, TRUST_KEY, self._data)
            except Exception as e:
                print(f"[Turso] training_wheels write failed, local JSON already has it: {e}")

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
