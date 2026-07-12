"""core/friday_memory.py — FRIDAY's memory system. Simpler than JARVIS's
six-type system, but personal: she remembers what matters about YOU.
Paths are anchored to the repo root (not cwd) so this works the same
whether run via `python server.py` or gunicorn from any working directory.

profile.json is Turso-backed (Render's disk is ephemeral — see
db/turso_client.py's module docstring); everything else in this file
(facts, conversations, emotional log, personal memory, notes) is still
local-JSON only pending its own migration stage. Profile's cache is
hydrated from Turso once at process start, then kept in sync write-
through on every update_profile() call. The old local-JSON path stays
as a fallback if Turso is unconfigured or a call fails."""
import json
from pathlib import Path
from datetime import datetime
from collections import Counter

from db import turso_client

BASE_DIR = Path(__file__).resolve().parent.parent
MEMORY_DIR = BASE_DIR / "memory"
FACTS_FILE = MEMORY_DIR / "facts.json"
CONVO_FILE = MEMORY_DIR / "conversations.json"
EMOTIONAL_FILE = MEMORY_DIR / "emotional_log.json"
PROFILE_FILE = MEMORY_DIR / "profile.json"
PERSONAL_FILE = MEMORY_DIR / "friday_personal.json"
NOTES_FILE = MEMORY_DIR / "friday_notes.json"

PROFILE_TABLE = "profile"
PROFILE_KEY = "profile"  # single-row kv table — profile is one flat dict, not many records
_profile_cache = None


_DICT_FILES = (PROFILE_FILE, PERSONAL_FILE)


def _load(path: Path):
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return {} if path in _DICT_FILES else []
    return {} if path in _DICT_FILES else []


def _save(path: Path, data):
    MEMORY_DIR.mkdir(exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ── Facts ────────────────────────────────────────────────────────────────────

def save_fact(fact: str):
    facts = _load(FACTS_FILE)
    if isinstance(facts, list) and fact not in facts:
        facts.append(fact)
        _save(FACTS_FILE, facts[-200:])


def get_facts(n: int = 10) -> list[str]:
    facts = _load(FACTS_FILE)
    return facts[-n:] if isinstance(facts, list) else []


# ── Conversations ────────────────────────────────────────────────────────────

def save_turn(user: str, friday: str):
    convos = _load(CONVO_FILE)
    if not isinstance(convos, list):
        convos = []
    convos.append({"user": user, "friday": friday, "ts": datetime.now().isoformat()})
    _save(CONVO_FILE, convos[-500:])


def get_recent_turns(n: int = 5) -> list[dict]:
    convos = _load(CONVO_FILE)
    return convos[-n:] if isinstance(convos, list) else []


def recall(query: str, k: int = 3) -> list[str]:
    """Simple keyword recall from conversation history."""
    convos = _load(CONVO_FILE)
    if not isinstance(convos, list):
        return []
    q_words = set(query.lower().split())
    scored = []
    for turn in convos:
        user_words = set(turn.get("user", "").lower().split())
        overlap = len(q_words & user_words)
        if overlap > 0:
            scored.append((overlap, turn))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [t["user"] + " -> " + t["friday"] for _, t in scored[:k]]


def get_context_for(query: str) -> str:
    facts = get_facts(5)
    recalled = recall(query, 3)
    parts = []
    if facts:
        parts.append("Known facts: " + "; ".join(facts))
    if recalled:
        parts.append("Recent relevant: " + " | ".join(recalled))
    return "\n".join(parts)


# ── Emotional log ────────────────────────────────────────────────────────────

def log_emotion(emotion: str, intensity: int, context: str):
    log = _load(EMOTIONAL_FILE)
    if not isinstance(log, list):
        log = []
    log.append({"emotion": emotion, "intensity": intensity, "context": context[:100],
                "ts": datetime.now().isoformat()})
    _save(EMOTIONAL_FILE, log[-200:])


def get_emotional_trend(days: int = 7) -> dict:
    """What's the emotional trend been recently? (days is accepted for API
    stability but not yet used for filtering — the log isn't large enough
    yet to need date-windowing over the most recent 20 entries.)"""
    log = _load(EMOTIONAL_FILE)
    if not isinstance(log, list) or not log:
        return {}
    emotions = [e["emotion"] for e in log[-20:]]
    return dict(Counter(emotions))


def get_mood_history(days: int = 7) -> dict:
    """Real date-windowed version of get_emotional_trend() — every logged
    entry already has an ISO timestamp (see log_emotion()), so this
    actually filters by day rather than just taking the most recent 20
    entries regardless of when they happened."""
    from datetime import timedelta
    log = _load(EMOTIONAL_FILE)
    if not isinstance(log, list) or not log:
        return {"dominant": "neutral", "avg_intensity": 0, "counts": {}, "entries": 0}

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    recent = [e for e in log if e.get("ts", "") >= cutoff]
    emotions = Counter(e["emotion"] for e in recent)
    avg_intensity = sum(e.get("intensity", 0) for e in recent) / max(len(recent), 1)

    return {
        "dominant": emotions.most_common(1)[0][0] if emotions else "neutral",
        "avg_intensity": round(avg_intensity, 1),
        "counts": dict(emotions),
        "entries": len(recent),
    }


# ── Profile ──────────────────────────────────────────────────────────────────

def get_profile() -> dict:
    global _profile_cache
    if _profile_cache is None:
        _profile_cache = _hydrate_profile()
    return _profile_cache


def update_profile(key: str, value):
    profile = get_profile()
    profile[key] = value
    _write_through_profile(profile)


def _hydrate_profile() -> dict:
    if turso_client.is_configured():
        try:
            existing = turso_client.kv_get(PROFILE_TABLE, PROFILE_KEY)
            return existing if existing is not None else {}
        except Exception as e:
            print(f"[FRIDAY] Turso hydrate failed for profile, falling back to local JSON: {e}")
    return _load(PROFILE_FILE)


def _write_through_profile(profile: dict):
    if turso_client.is_configured():
        try:
            turso_client.kv_set(PROFILE_TABLE, PROFILE_KEY, profile)
            return
        except Exception as e:
            print(f"[FRIDAY] Turso write failed for profile, falling back to local JSON: {e}")
    _save(PROFILE_FILE, profile)


# ── Personal memory ──────────────────────────────────────────────────────────
# Keyed lookup, distinct from get_facts()'s flat list — for the kind of
# thing you'd want back by name ("what's my usual coffee order") rather
# than surfaced by keyword-scan relevance.

def friday_remember(key: str, value: str):
    data = _load(PERSONAL_FILE)
    if not isinstance(data, dict):
        data = {}
    data[key] = {"value": value, "ts": datetime.now().isoformat()}
    _save(PERSONAL_FILE, data)


def friday_recall(key: str) -> str | None:
    data = _load(PERSONAL_FILE)
    if not isinstance(data, dict):
        return None
    entry = data.get(key)
    return entry.get("value") if entry else None


# ── Notes ("note that") — Turso-backed, same pattern as profile above ───────
# Note: the old 500-cap only bounded the local JSON file's size; Turso's
# list_insert has no equivalent trim, so the table itself grows unbounded
# over time even though the in-memory cache below still caps at 500 for
# read consistency. Not adding pruning logic for this pass — flagging it
# rather than deciding unilaterally to add retention/deletion behavior
# that wasn't asked for.

NOTES_TABLE = "notes"
_notes_cache = None


def save_note(note: dict):
    global _notes_cache
    if _notes_cache is None:
        _notes_cache = _hydrate_notes()
    _write_through_notes(note)  # may attach a Turso-assigned "id" to `note` in place
    _notes_cache.append(note)
    _notes_cache = _notes_cache[-500:]


def get_notes(limit: int = 10) -> list:
    global _notes_cache
    if _notes_cache is None:
        _notes_cache = _hydrate_notes()
    return _notes_cache[-limit:]


def _hydrate_notes() -> list:
    if turso_client.is_configured():
        try:
            return turso_client.list_all(NOTES_TABLE)
        except Exception as e:
            print(f"[FRIDAY] Turso hydrate failed for notes, falling back to local JSON: {e}")
    notes = _load(NOTES_FILE)
    return notes if isinstance(notes, list) else []


def _write_through_notes(note: dict):
    if turso_client.is_configured():
        try:
            note["id"] = turso_client.list_insert(NOTES_TABLE, note)
        except Exception as e:
            print(f"[FRIDAY] Turso write failed for notes, falling back to local JSON: {e}")
            _save(NOTES_FILE, _notes_cache + [note])
            return
        # Trim is best-effort and separate from the write above — the note
        # is already safely stored, so a trim failure here is an unbounded-
        # growth concern, not a data-loss one, and shouldn't fall back to
        # also writing local JSON on top of an already-successful insert.
        try:
            turso_client.list_trim(NOTES_TABLE, 500)
        except Exception as e:
            print(f"[FRIDAY] Turso trim failed for notes (non-fatal): {e}")
        return
    _save(NOTES_FILE, _notes_cache + [note])
