"""core/friday_memory.py — FRIDAY's memory system. Simpler than JARVIS's
six-type system, but personal: she remembers what matters about YOU.
Paths are anchored to the repo root (not cwd) so this works the same
whether run via `python server.py` or gunicorn from any working directory."""
import json
from pathlib import Path
from datetime import datetime
from collections import Counter

from db import turso_http_client as turso

BASE_DIR = Path(__file__).resolve().parent.parent
MEMORY_DIR = BASE_DIR / "memory"
FACTS_FILE = MEMORY_DIR / "facts.json"
CONVO_FILE = MEMORY_DIR / "conversations.json"
EMOTIONAL_FILE = MEMORY_DIR / "emotional_log.json"
PROFILE_FILE = MEMORY_DIR / "profile.json"
PERSONAL_FILE = MEMORY_DIR / "friday_personal.json"
NOTES_FILE = MEMORY_DIR / "friday_notes.json"


_DICT_FILES = (PROFILE_FILE, PERSONAL_FILE)

# Turso table names for the durable copies of conversations/facts/profile.
# These three back the main conversational memory path (get_context_for()
# -> friday_brain.think() -> save_turn(), used on every default chat turn)
# and were local-JSON-only until this migration — fine on a machine with a
# real disk, but Render's web service filesystem isn't guaranteed to
# survive a restart or redeploy, so every restart silently reset FRIDAY's
# memory of every past conversation and fact. notes (below) already had
# this Turso write-through/fallback/seed pattern; this applies the same
# one here.
CONVOS_TABLE = "conversations"
FACTS_TABLE = "facts"
PROFILE_TABLE = "profile"


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

def _load_facts() -> list[str]:
    """Turso first (durable across restarts), local JSON as fallback and
    as the seed source the first time a Turso table comes up empty —
    same shape as get_notes() below."""
    if turso.is_configured():
        rows = None
        try:
            turso.ensure_list_table(FACTS_TABLE)
            rows = turso.list_all(FACTS_TABLE)
        except Exception as e:
            print(f"[Turso] facts read failed, falling back to local JSON: {e}")
        if rows:
            return [r["fact"] for r in rows]
        if rows is not None:
            local = _load(FACTS_FILE)
            if not isinstance(local, list):
                local = []
            for fact in local:
                try:
                    turso.list_insert(FACTS_TABLE, {"fact": fact})
                except Exception as e:
                    print(f"[Turso] facts seed failed: {e}")
            return local

    facts = _load(FACTS_FILE)
    return facts if isinstance(facts, list) else []


def save_fact(fact: str):
    if fact in _load_facts():
        return
    local = _load(FACTS_FILE)
    if not isinstance(local, list):
        local = []
    if fact not in local:
        local.append(fact)
        _save(FACTS_FILE, local[-200:])

    if turso.is_configured():
        try:
            turso.ensure_list_table(FACTS_TABLE)
            turso.list_insert(FACTS_TABLE, {"fact": fact})
        except Exception as e:
            print(f"[Turso] fact write failed, local JSON already has it: {e}")


def get_facts(n: int = 10) -> list[str]:
    return _load_facts()[-n:]


# ── Conversations ────────────────────────────────────────────────────────────

def _load_convos() -> list[dict]:
    """Turso first (durable across restarts), local JSON as fallback/seed —
    this is the list get_context_for() draws "recent relevant" turns from
    on every default chat reply, so losing it on every restart is exactly
    what "FRIDAY forgets conversations" looks like from the outside."""
    if turso.is_configured():
        rows = None
        try:
            turso.ensure_list_table(CONVOS_TABLE)
            rows = turso.list_all(CONVOS_TABLE)
        except Exception as e:
            print(f"[Turso] conversation read failed, falling back to local JSON: {e}")
        if rows:
            return rows
        if rows is not None:
            local = _load(CONVO_FILE)
            if not isinstance(local, list):
                local = []
            for record in local:
                try:
                    turso.list_insert(CONVOS_TABLE, record)
                except Exception as e:
                    print(f"[Turso] conversation seed failed: {e}")
            return local

    convos = _load(CONVO_FILE)
    return convos if isinstance(convos, list) else []


def save_turn(user: str, friday: str):
    turn = {"user": user, "friday": friday, "ts": datetime.now().isoformat()}
    convos = _load(CONVO_FILE)
    if not isinstance(convos, list):
        convos = []
    convos.append(turn)
    _save(CONVO_FILE, convos[-500:])

    if turso.is_configured():
        try:
            turso.ensure_list_table(CONVOS_TABLE)
            turso.list_insert(CONVOS_TABLE, turn)
        except Exception as e:
            print(f"[Turso] conversation write failed, local JSON already has it: {e}")


def get_recent_turns(n: int = 5) -> list[dict]:
    return _load_convos()[-n:]


def recall(query: str, k: int = 3) -> list[str]:
    """Simple keyword recall from conversation history."""
    convos = _load_convos()
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
    if turso.is_configured():
        try:
            turso.ensure_kv_table(PROFILE_TABLE)
            data = turso.kv_get(PROFILE_TABLE, "profile")
            if data is not None:
                return data
        except Exception as e:
            print(f"[Turso] profile read failed, falling back to local JSON: {e}")
        local = _load(PROFILE_FILE)
        if isinstance(local, dict) and local:
            try:
                turso.kv_set(PROFILE_TABLE, "profile", local)
            except Exception as e:
                print(f"[Turso] profile seed failed: {e}")
        return local if isinstance(local, dict) else {}
    return _load(PROFILE_FILE)


def update_profile(key: str, value):
    profile = get_profile()
    profile[key] = value
    _save(PROFILE_FILE, profile)
    if turso.is_configured():
        try:
            turso.ensure_kv_table(PROFILE_TABLE)
            turso.kv_set(PROFILE_TABLE, "profile", profile)
        except Exception as e:
            print(f"[Turso] profile write failed, local JSON already has it: {e}")


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


# ── Notes ("note that") ──────────────────────────────────────────────────────

NOTES_TABLE = "notes"


def save_note(note: dict):
    notes = _load(NOTES_FILE)
    if not isinstance(notes, list):
        notes = []
    notes.append(note)
    notes = notes[-500:]
    _save(NOTES_FILE, notes)

    if turso.is_configured():
        try:
            turso.ensure_list_table(NOTES_TABLE)
            turso.list_insert(NOTES_TABLE, note)
        except Exception as e:
            print(f"[Turso] note write failed, local JSON already has it: {e}")


def get_notes(limit: int = 10) -> list:
    if turso.is_configured():
        rows = None
        try:
            turso.ensure_list_table(NOTES_TABLE)
            rows = turso.list_all(NOTES_TABLE)
        except Exception as e:
            print(f"[Turso] notes read failed, falling back to local JSON: {e}")
        if rows:
            return rows[-limit:]
        if rows is not None:
            # Query succeeded but came back empty — either genuinely no
            # notes yet, or this is the first read since migrating and
            # Turso hasn't been seeded from the pre-existing local JSON.
            local = _load(NOTES_FILE)
            if not isinstance(local, list):
                local = []
            for record in local:
                try:
                    turso.list_insert(NOTES_TABLE, record)
                except Exception as e:
                    print(f"[Turso] notes seed failed: {e}")
            return local[-limit:]

    notes = _load(NOTES_FILE)
    if not isinstance(notes, list):
        return []
    return notes[-limit:]
