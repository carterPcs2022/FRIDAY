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

FACTS_TABLE = "facts"


def save_fact(fact: str):
    facts = _load(FACTS_FILE)
    if not isinstance(facts, list):
        facts = []
    if fact in facts:
        return
    facts.append(fact)
    facts = facts[-200:]
    _save(FACTS_FILE, facts)

    if turso.is_configured():
        try:
            turso.ensure_list_table(FACTS_TABLE)
            turso.list_insert(FACTS_TABLE, {"fact": fact})
        except Exception as e:
            print(f"[Turso] fact write failed, local JSON already has it: {e}")


def get_facts(n: int = 10) -> list[str]:
    if turso.is_configured():
        rows = None
        try:
            turso.ensure_list_table(FACTS_TABLE)
            rows = turso.list_all(FACTS_TABLE)
        except Exception as e:
            print(f"[Turso] facts read failed, falling back to local JSON: {e}")
        if rows:
            facts = [r["fact"] for r in rows if "fact" in r]
            return facts[-n:]
        if rows is not None:
            # Query succeeded but came back empty — either genuinely no
            # facts yet, or this is the first read since migrating and
            # Turso hasn't been seeded from the pre-existing local JSON.
            local = _load(FACTS_FILE)
            local = local if isinstance(local, list) else []
            for fact in local:
                try:
                    turso.list_insert(FACTS_TABLE, {"fact": fact})
                except Exception as e:
                    print(f"[Turso] facts seed failed: {e}")
            return local[-n:]

    facts = _load(FACTS_FILE)
    return facts[-n:] if isinstance(facts, list) else []


# ── Conversations ────────────────────────────────────────────────────────────

CONVO_TABLE = "conversations"


def save_turn(user: str, friday: str):
    convos = _load(CONVO_FILE)
    if not isinstance(convos, list):
        convos = []
    turn = {"user": user, "friday": friday, "ts": datetime.now().isoformat()}
    convos.append(turn)
    convos = convos[-500:]
    _save(CONVO_FILE, convos)

    if turso.is_configured():
        try:
            turso.ensure_list_table(CONVO_TABLE)
            turso.list_insert(CONVO_TABLE, turn)
        except Exception as e:
            print(f"[Turso] conversation write failed, local JSON already has it: {e}")


def get_recent_turns(n: int = 5) -> list[dict]:
    if turso.is_configured():
        rows = None
        try:
            turso.ensure_list_table(CONVO_TABLE)
            rows = turso.list_all(CONVO_TABLE)
        except Exception as e:
            print(f"[Turso] conversations read failed, falling back to local JSON: {e}")
        if rows:
            return rows[-n:]
        if rows is not None:
            local = _load(CONVO_FILE)
            local = local if isinstance(local, list) else []
            for turn in local:
                try:
                    turso.list_insert(CONVO_TABLE, turn)
                except Exception as e:
                    print(f"[Turso] conversations seed failed: {e}")
            return local[-n:]

    convos = _load(CONVO_FILE)
    return convos[-n:] if isinstance(convos, list) else []


def recall(query: str, k: int = 3) -> list[str]:
    """Simple keyword recall from conversation history. Goes through
    get_recent_turns() (not a raw local-file load) so it sees Turso-backed
    history too — reading CONVO_FILE directly here would show nothing
    after a Render redeploy wipes it, even though Turso still has it."""
    convos = get_recent_turns(500)
    if not convos:
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

EMOTIONAL_TABLE = "emotional_log"


def log_emotion(emotion: str, intensity: int, context: str):
    log = _load(EMOTIONAL_FILE)
    if not isinstance(log, list):
        log = []
    entry = {"emotion": emotion, "intensity": intensity, "context": context[:100],
              "ts": datetime.now().isoformat()}
    log.append(entry)
    log = log[-200:]
    _save(EMOTIONAL_FILE, log)

    if turso.is_configured():
        try:
            turso.ensure_list_table(EMOTIONAL_TABLE)
            turso.list_insert(EMOTIONAL_TABLE, entry)
        except Exception as e:
            print(f"[Turso] emotion write failed, local JSON already has it: {e}")


def _get_emotional_log(limit: int = 200) -> list[dict]:
    """Turso-backed read with local-JSON seed-on-empty fallback, same
    shape as get_notes()/get_recent_turns(). Both get_emotional_trend()
    and get_mood_history() go through this instead of loading
    EMOTIONAL_FILE directly, so both see Turso-backed history too."""
    if turso.is_configured():
        rows = None
        try:
            turso.ensure_list_table(EMOTIONAL_TABLE)
            rows = turso.list_all(EMOTIONAL_TABLE)
        except Exception as e:
            print(f"[Turso] emotional log read failed, falling back to local JSON: {e}")
        if rows:
            return rows[-limit:]
        if rows is not None:
            local = _load(EMOTIONAL_FILE)
            local = local if isinstance(local, list) else []
            for entry in local:
                try:
                    turso.list_insert(EMOTIONAL_TABLE, entry)
                except Exception as e:
                    print(f"[Turso] emotional log seed failed: {e}")
            return local[-limit:]

    log = _load(EMOTIONAL_FILE)
    return log[-limit:] if isinstance(log, list) else []


def get_emotional_trend(days: int = 7) -> dict:
    """What's the emotional trend been recently? (days is accepted for API
    stability but not yet used for filtering — the log isn't large enough
    yet to need date-windowing over the most recent 20 entries.)"""
    log = _get_emotional_log(20)
    if not log:
        return {}
    emotions = [e["emotion"] for e in log]
    return dict(Counter(emotions))


def get_mood_history(days: int = 7) -> dict:
    """Real date-windowed version of get_emotional_trend() — every logged
    entry already has an ISO timestamp (see log_emotion()), so this
    actually filters by day rather than just taking the most recent 20
    entries regardless of when they happened."""
    from datetime import timedelta
    log = _get_emotional_log()
    if not log:
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
# Read on nearly every request, so this was deliberately saved for last in
# the migration — a single kv row (whole profile dict under one fixed key)
# rather than list_* records, since it's inherently one object, not a
# growing history.

PROFILE_TABLE = "profile"
PROFILE_KEY = "profile"


def get_profile() -> dict:
    if turso.is_configured():
        row, query_ok = None, False
        try:
            turso.ensure_kv_table(PROFILE_TABLE)
            row = turso.kv_get(PROFILE_TABLE, PROFILE_KEY)
            query_ok = True
        except Exception as e:
            print(f"[Turso] profile read failed, falling back to local JSON: {e}")

        if row is not None:
            # Turso has a row — even an empty dict is a real answer, not
            # "no data yet" (unlike kv_get's None, which unambiguously
            # means the key was never written).
            return row
        if query_ok:
            # Query succeeded but the key doesn't exist yet — first read
            # since migrating, seed Turso from local JSON.
            local = _load(PROFILE_FILE)
            if isinstance(local, dict) and local:
                try:
                    turso.kv_set(PROFILE_TABLE, PROFILE_KEY, local)
                except Exception as e:
                    print(f"[Turso] profile seed failed: {e}")
            return local

    return _load(PROFILE_FILE)


def update_profile(key: str, value):
    profile = get_profile()
    profile[key] = value
    _save(PROFILE_FILE, profile)

    if turso.is_configured():
        try:
            turso.ensure_kv_table(PROFILE_TABLE)
            turso.kv_set(PROFILE_TABLE, PROFILE_KEY, profile)
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
