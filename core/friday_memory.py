"""core/friday_memory.py — FRIDAY's memory system. Simpler than JARVIS's
six-type system, but personal: she remembers what matters about YOU.
Paths are anchored to the repo root (not cwd) so this works the same
whether run via `python server.py` or gunicorn from any working directory."""
import json
from pathlib import Path
from datetime import datetime
from collections import Counter

BASE_DIR = Path(__file__).resolve().parent.parent
MEMORY_DIR = BASE_DIR / "memory"
FACTS_FILE = MEMORY_DIR / "facts.json"
CONVO_FILE = MEMORY_DIR / "conversations.json"
EMOTIONAL_FILE = MEMORY_DIR / "emotional_log.json"
PROFILE_FILE = MEMORY_DIR / "profile.json"


def _load(path: Path):
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return [] if path != PROFILE_FILE else {}
    return [] if path != PROFILE_FILE else {}


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


# ── Profile ──────────────────────────────────────────────────────────────────

def get_profile() -> dict:
    return _load(PROFILE_FILE)


def update_profile(key: str, value):
    profile = get_profile()
    profile[key] = value
    _save(PROFILE_FILE, profile)
