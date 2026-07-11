"""services/system_doctor.py — a single "how's everything actually
doing" check the boss (or FRIDAY herself, via the "run diagnostics"
trigger) can pull on demand, instead of piecing it together from five
separate /friday/* routes each time something feels off.
"""
import os
import shutil
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
MEMORY_DIR = BASE_DIR / "memory"

# Same set friday_capabilities._pushover_alert / the rest of the repo
# treat as "the free-tier LLM providers" — checked here purely for
# presence, not validity (config_validator already flags placeholders).
_API_KEYS = ["ANTHROPIC_API_KEY", "GROQ_API_KEY", "ELEVENLABS_API_KEY"]

# Memory files the rest of the app assumes exist and are valid JSON —
# a corrupted one (partial write during a crash, say) fails silently
# wherever it's read since most readers wrap json.loads in a bare
# except and fall back to an empty default.
_MEMORY_FILES = [
    "conversations.json", "friday_baseline.json", "friday_bills.json",
    "friday_goals.json", "friday_habits.json", "friday_journal.json",
    "friday_knowledge.json", "friday_notes.json", "friday_patterns.json",
    "friday_people.json", "friday_tasks.json", "friday_workouts.json",
    "profile.json", "second_brain.json", "voice_profile.json",
]


def _check_apis() -> dict:
    present = {key: bool(os.environ.get(key, "")) for key in _API_KEYS}
    return {"ok": any(present.values()), "keys": present}


def _check_mac_bridge() -> dict:
    mac_url = os.environ.get("MAC_BRIDGE_URL", "")
    if not mac_url:
        return {"ok": None, "reason": "not configured"}
    try:
        import httpx
        r = httpx.get(
            f"{mac_url}/mac/battery", timeout=5,
            headers={"Authorization": f"Bearer {os.environ.get('MAC_BRIDGE_TOKEN', '')}"},
        )
        return {"ok": r.status_code == 200, "status_code": r.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _check_disk() -> dict:
    try:
        total, used, free = shutil.disk_usage(BASE_DIR)
        pct_used = round(used / total * 100, 1)
        return {"ok": pct_used < 90, "pct_used": pct_used, "free_mb": round(free / 1024 / 1024, 1)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _check_memory_files() -> dict:
    missing = []
    corrupt = []
    for name in _MEMORY_FILES:
        path = MEMORY_DIR / name
        if not path.exists():
            missing.append(name)
            continue
        try:
            json.loads(path.read_text())
        except Exception:
            corrupt.append(name)
    return {"ok": not corrupt, "missing": missing, "corrupt": corrupt}


def _check_config() -> dict:
    try:
        from core.config_validator import check
        return check()
    except Exception as e:
        return {"ok": False, "issues": [f"config_validator failed: {e}"]}


def full_check() -> dict:
    """Never raises — a doctor that crashes when asked how the patient's
    doing is worse than useless."""
    checks = {
        "apis": _check_apis(),
        "mac_bridge": _check_mac_bridge(),
        "disk": _check_disk(),
        "memory_files": _check_memory_files(),
        "config": _check_config(),
    }
    # mac_bridge's ok=None (not configured) shouldn't count as unhealthy —
    # only an explicit False across any check should.
    healthy = all(c.get("ok") is not False for c in checks.values())
    return {"healthy": healthy, "checks": checks}
