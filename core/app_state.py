"""core/app_state.py — the shared runtime state server.py's routes/*.py
blueprints and server.py's own core orchestration (/command, the startup
background threads) both need: every optional service singleton (each
still guarded by its own try/except, exactly as before this split --
one broken service module must not be able to take the rest of the app
down with it), plus the small set of helpers/constants genuinely used
from more than one of those files (_log, safe(), get_tasks()/add_task(),
EXCHANGE_LOG, _FOCUS_SESSION, LOCKDOWN_TRIGGERS, and the task/workout
Turso-backed data access).

This is what makes the blueprint split possible without circular
imports: routes/*.py modules import from here, never from server.py;
server.py imports from here too (via `from core.app_state import *`,
right where this block used to live inline), so /command's existing
code keeps referencing these exact same bare names, unchanged.

__all__ below is deliberately explicit and includes the underscore-
prefixed names (_log, _push, _FOCUS_SESSION, ...) — Python's `import *`
silently *skips* underscore-prefixed names without an explicit __all__,
which would otherwise quietly break every one of those references the
moment server.py switched to a star-import.
"""
import json
import logging
import datetime
import threading
from collections import deque
from pathlib import Path

from db import turso_http_client as turso

EXCHANGE_LOG = deque(maxlen=10)
BASE_DIR = Path(__file__).resolve().parent.parent


# ── Core loading — each guarded individually so one failing module can't
# take the others (or the app) down with it ──────────────────────────────────
try:
    from core.friday_brain import friday_brain
    BRAIN_OK = True
except Exception as e:
    friday_brain = None
    BRAIN_OK = False
    logging.warning(f"Brain failed: {e}")

try:
    from core.emotional_intel import emotional_intel
    EMOTIONAL_OK = True
except Exception as e:
    emotional_intel = None
    EMOTIONAL_OK = False
    logging.warning(f"Emotional intelligence failed: {e}")

try:
    from core.friday_memory import (
        save_turn, get_recent_turns, get_context_for,
        save_fact, log_emotion, get_emotional_trend, get_profile,
        get_mood_history, friday_remember, friday_recall,
    )
    MEMORY_OK = True
except Exception as e:
    MEMORY_OK = False
    logging.warning(f"Memory failed: {e}")

CORE_STATUS = "online" if (BRAIN_OK and EMOTIONAL_OK and MEMORY_OK) else "degraded"
if CORE_STATUS == "online":
    logging.info("Brain and emotional intelligence online")

# ── Voice ────────────────────────────────────────────────────────────────────
try:
    from services.friday_voice import speak as friday_speak
    VOICE_OK = True
except Exception as e:
    friday_speak = lambda *a, **k: None
    VOICE_OK = False
    logging.warning(f"Voice failed: {e}")

try:
    from services.voice_transcribe import transcribe_audio
    TRANSCRIBE_OK = True
except Exception as e:
    transcribe_audio = None
    TRANSCRIBE_OK = False
    logging.warning(f"Voice transcription failed: {e}")

# ── Training (learns from JARVIS) + range protocols ──────────────────────────
try:
    from core.friday_training import friday_trainer
    TRAINING_OK = True
except Exception as e:
    friday_trainer = None
    TRAINING_OK = False
    logging.warning(f"Training failed: {e}")

try:
    from services.wisdom import get_wisdom_context
    WISDOM_OK = True
except Exception as e:
    get_wisdom_context = None
    WISDOM_OK = False
    logging.warning(f"Wisdom context failed: {e}")

try:
    from core.friday_protocols import friday_protocols, RangeLevel
    PROTOCOLS_OK = True
except Exception as e:
    friday_protocols = None
    RangeLevel = None
    PROTOCOLS_OK = False
    logging.warning(f"Protocols failed: {e}")

try:
    from core.veronica import veronica
    VERONICA_OK = True
except Exception as e:
    veronica = None
    VERONICA_OK = False
    logging.warning(f"Veronica failed: {e}")

try:
    from core.friday_capabilities import CAPABILITY_MAP, friday_caps
    CAPABILITIES_OK = True
except Exception as e:
    CAPABILITY_MAP = {}
    friday_caps = None
    CAPABILITIES_OK = False
    logging.warning(f"Capabilities failed: {e}")

try:
    from services.friday_health import friday_health
    HEALTH_OK = True
except Exception as e:
    friday_health = None
    HEALTH_OK = False
    logging.warning(f"Health monitor failed: {e}")

try:
    from services.friday_contacts import friday_contacts
    CONTACTS_OK = True
except Exception as e:
    friday_contacts = None
    CONTACTS_OK = False
    logging.warning(f"Contacts failed: {e}")

try:
    from services.team_coordinator import team
    TEAM_OK = True
except Exception as e:
    team = None
    TEAM_OK = False
    logging.warning(f"Team coordinator failed: {e}")

try:
    from services.second_brain import second_brain
except Exception as e:
    second_brain = None
    logging.warning(f"Second brain failed: {e}")

try:
    from services.friday_news import news_anchor
except Exception as e:
    news_anchor = None
    logging.warning(f"News anchor failed: {e}")

try:
    from services.friday_relationships import relationships
except Exception as e:
    relationships = None
    logging.warning(f"Relationships failed: {e}")

try:
    from services.friday_code import friday_code
except Exception as e:
    friday_code = None
    logging.warning(f"Code intel failed: {e}")

try:
    from services.friday_translate import translator
except Exception as e:
    translator = None
    logging.warning(f"Translator failed: {e}")

try:
    from services.career import career
except Exception as e:
    career = None
    logging.warning(f"Career assistant failed: {e}")

try:
    from services.decisions import decisions
except Exception as e:
    decisions = None
    logging.warning(f"Decision support failed: {e}")

try:
    from services.finance import finance
except Exception as e:
    finance = None
    logging.warning(f"Finance intelligence failed: {e}")

try:
    from services.legal import legal
except Exception as e:
    legal = None
    logging.warning(f"Legal analyzer failed: {e}")

try:
    from services.reading_memory import reading_mem
except Exception as e:
    reading_mem = None
    logging.warning(f"Reading memory failed: {e}")

try:
    from services.social_intel import social
except Exception as e:
    social = None
    logging.warning(f"Social intelligence failed: {e}")

try:
    from services.tutor import tutor
except Exception as e:
    tutor = None
    logging.warning(f"Tutor failed: {e}")

try:
    from services.hierarchical_planning import hierarchical
except Exception as e:
    hierarchical = None
    logging.warning(f"Hierarchical planning failed: {e}")

try:
    from services.friday_medicine import medicine_tracker
except Exception as e:
    medicine_tracker = None
    logging.warning(f"Medicine tracker failed: {e}")

try:
    from services.voice_memory import voice_memory
except Exception as e:
    voice_memory = None
    logging.warning(f"Voice memory failed: {e}")

try:
    from services.friday_gmail import friday_gmail
except Exception as e:
    friday_gmail = None
    logging.warning(f"Gmail failed: {e}")

try:
    from services.friday_spotify import friday_spotify
except Exception as e:
    friday_spotify = None
    logging.warning(f"Spotify failed: {e}")

try:
    from services.friday_habits import habits
except Exception as e:
    habits = None
    logging.warning(f"Habits failed: {e}")

try:
    from services.friday_journal import journal
except Exception as e:
    journal = None
    logging.warning(f"Journal failed: {e}")

try:
    from services.friday_calendar import friday_calendar
except Exception as e:
    friday_calendar = None
    logging.warning(f"Calendar failed: {e}")

try:
    from services.friday_continuity import continuity
except Exception as e:
    continuity = None
    logging.warning(f"Continuity failed: {e}")

try:
    from services.friday_goals import goals
except Exception as e:
    goals = None
    logging.warning(f"Goals failed: {e}")

try:
    from services.friday_vision import friday_vision
except Exception as e:
    friday_vision = None
    logging.warning(f"Vision failed: {e}")

try:
    from services.friday_calibration import calibration
except Exception as e:
    calibration = None
    logging.warning(f"Calibration failed: {e}")

try:
    from services.cross_check import cross_check
except Exception as e:
    cross_check = None
    logging.warning(f"Cross-check failed: {e}")

try:
    from services.training_wheels import training_wheels
    TRAINING_WHEELS_OK = True
except Exception as e:
    training_wheels = None
    TRAINING_WHEELS_OK = False
    logging.warning(f"Training wheels failed: {e}")

try:
    from services.recognizance import recognizance
    RECON_OK = True
except Exception as e:
    recognizance = None
    RECON_OK = False
    logging.warning(f"Recognizance failed: {e}")

try:
    from services.checkin_system import checkin_system
    CHECKIN_OK = True
except Exception as e:
    checkin_system = None
    CHECKIN_OK = False
    logging.warning(f"Check-in system failed: {e}")

try:
    from services.suit_lockdown import suit_lockdown
    LOCKDOWN_OK = True
except Exception as e:
    suit_lockdown = None
    LOCKDOWN_OK = False
    logging.warning(f"Suit lockdown failed: {e}")

try:
    from services.ha_client import home_assistant
    HA_OK = True
except Exception as e:
    home_assistant = None
    HA_OK = False
    logging.warning(f"Home Assistant client failed: {e}")

try:
    from services.friday_hud import spawn_widget, drain_widgets
    HUD_OK = True
except Exception as e:
    HUD_OK = False
    logging.warning(f"HUD widget queue failed: {e}")

    def spawn_widget(*a, **k):  # HUD unavailable — spawn calls become no-ops
        return None


def _extract_topic(prompt: str) -> str:
    TOPIC_KEYWORDS = {
        "project": "project", "work": "work", "meeting": "meeting",
        "family": "family", "health": "health", "money": "finances",
        "jarvis": "JARVIS build", "suit": "Iron Man suit",
        "friday": "FRIDAY build", "code": "coding", "deploy": "deployment",
    }
    p = prompt.lower()
    for keyword, topic in TOPIC_KEYWORDS.items():
        if keyword in p:
            return topic
    return ""

try:
    from services.friday_security import friday_security
    SECURITY_OK = True
except Exception as e:
    friday_security = None
    SECURITY_OK = False
    logging.warning(f"Security failed: {e}")

try:
    from services.hulkbuster import hulkbuster
    HULKBUSTER_OK = True
except Exception as e:
    hulkbuster = None
    HULKBUSTER_OK = False
    logging.warning(f"HulkBuster failed: {e}")

try:
    from core.scatter import get_engine as _get_scatter_engine
    scatter_engine = _get_scatter_engine()
    SCATTER_OK = True
except Exception as e:
    scatter_engine = None
    SCATTER_OK = False
    logging.warning(f"Scatter Protocol failed: {e}")

# Read by core/autonomous_agent.py's _alert() (imported at call time, not
# module load, to avoid a circular import) to hold non-urgent alerts
# during an active focus session.
_FOCUS_SESSION = {"active": False, "task": "", "end_time": 0}

def _push(title: str, message: str, priority=None):
    """Routes through services/notifications.py. priority accepts a
    notifications.Priority value; defaults to HIGH (still reaches
    Pushover) since every real caller here is either time-sensitive (a
    reminder the boss explicitly set, a focus-session timer) or
    deliberately rate-limited and personally relevant (the proactive
    emotional check-in) — Morning Brief is the one routine exception and
    passes WARNING explicitly (HUD only, not a push notification)."""
    try:
        from services.notifications import notify, Priority
        notify(title, message, priority if priority is not None else Priority.HIGH)
    except Exception as e:
        logging.warning(f"Push notify failed: {e}")


# Module-level (not local to command()) so friday_voice_transcribe() can
# apply the same list when deciding whether a voice-originated lockdown
# phrase needs a positively-verified speaker before it's even allowed to
# reach command() as text — see that route for why.
LOCKDOWN_TRIGGERS = ["lockdown now", "emergency lockdown", "lock the system", "suit lockdown"]

TASK_FILE = Path("memory/friday_tasks.json")
WORKOUT_FILE = Path("memory/friday_workouts.json")

WORKOUT_TABLE = "workouts"


def log_workout(workout_type: str, duration: int = 0):
    record = {
        "type": workout_type, "duration": duration,
        "ts": datetime.datetime.now().isoformat(),
    }

    # Local JSON stays the write-through cache during the observation
    # window for this file's migration — Turso is the new source of
    # truth, but a write here means we never lose data even if Turso
    # is having a bad day.
    workouts = []
    if WORKOUT_FILE.exists():
        try:
            workouts = json.loads(WORKOUT_FILE.read_text())
        except Exception:
            workouts = []
    workouts.append(record)
    WORKOUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    WORKOUT_FILE.write_text(json.dumps(workouts[-365:], indent=2))

    if turso.is_configured():
        try:
            turso.ensure_list_table(WORKOUT_TABLE)
            turso.list_insert(WORKOUT_TABLE, record)
        except Exception as e:
            print(f"[Turso] workout write failed, local JSON already has it: {e}")


def _read_local_workouts() -> list:
    if WORKOUT_FILE.exists():
        try:
            return json.loads(WORKOUT_FILE.read_text())
        except Exception:
            return []
    return []


def get_workouts() -> list:
    if turso.is_configured():
        rows = None
        try:
            turso.ensure_list_table(WORKOUT_TABLE)
            rows = turso.list_all(WORKOUT_TABLE)
        except Exception as e:
            print(f"[Turso] workout read failed, falling back to local JSON: {e}")
        if rows:
            return rows
        if rows is not None:
            # Query succeeded but came back empty — either genuinely no
            # workouts yet, or this is the first read since migrating and
            # Turso hasn't been seeded from the pre-existing local JSON.
            # Backfill once so history isn't invisible after a redeploy
            # wipes the local file.
            local = _read_local_workouts()
            for record in local:
                try:
                    turso.list_insert(WORKOUT_TABLE, record)
                except Exception as e:
                    print(f"[Turso] workout seed failed: {e}")
            return local
    return _read_local_workouts()



TASKS_TABLE = "tasks"


def _read_local_tasks() -> list:
    if TASK_FILE.exists():
        try:
            return json.loads(TASK_FILE.read_text())
        except Exception:
            return []
    return []


def _write_local_tasks(tasks: list):
    TASK_FILE.parent.mkdir(parents=True, exist_ok=True)
    TASK_FILE.write_text(json.dumps(tasks, indent=2))


def get_tasks() -> list:
    if turso.is_configured():
        rows = None
        try:
            turso.ensure_list_table(TASKS_TABLE)
            rows = turso.list_all(TASKS_TABLE)
        except Exception as e:
            print(f"[Turso] tasks read failed, falling back to local JSON: {e}")
        if rows:
            return rows
        if rows is not None:
            local = _read_local_tasks()
            for record in local:
                try:
                    turso.list_insert(TASKS_TABLE, {k: v for k, v in record.items() if k != "id"})
                except Exception as e:
                    print(f"[Turso] tasks seed failed: {e}")
            # Unlike the append-only files, tasks are mutated by id
            # (complete_task), so the ids handed back here must be Turso's
            # own row ids from this point on -- re-read post-seed instead
            # of returning the locally-numbered `local` list.
            try:
                return turso.list_all(TASKS_TABLE)
            except Exception as e:
                print(f"[Turso] tasks re-read after seed failed: {e}")
            return local
    return _read_local_tasks()


def add_task(task: str, priority: str = "normal") -> dict:
    tasks = get_tasks()
    new_task = {
        "task": task, "priority": priority,
        "done": False, "added": datetime.datetime.now().isoformat(),
    }

    if turso.is_configured():
        try:
            turso.ensure_list_table(TASKS_TABLE)
            new_task["id"] = turso.list_insert(TASKS_TABLE, new_task)
        except Exception as e:
            print(f"[Turso] task write failed, local JSON already has it: {e}")

    if "id" not in new_task:
        new_task["id"] = len(tasks) + 1

    local_tasks = _read_local_tasks()
    local_tasks.append(new_task)
    _write_local_tasks(local_tasks)
    return new_task


def complete_task(task_id: int):
    local_tasks = _read_local_tasks()
    for t in local_tasks:
        if t.get("id") == task_id:
            t["done"] = True
            t["completed"] = datetime.datetime.now().isoformat()
    _write_local_tasks(local_tasks)

    if turso.is_configured():
        try:
            turso.ensure_list_table(TASKS_TABLE)
            for t in get_tasks():
                if t.get("id") == task_id:
                    t["done"] = True
                    t["completed"] = datetime.datetime.now().isoformat()
                    turso.list_update(TASKS_TABLE, task_id, t)
                    break
        except Exception as e:
            print(f"[Turso] task complete write failed, local JSON already has it: {e}")


def add_reminder(text: str, minutes: int):
    """Fires _push() (the same real Pushover helper everything else in
    this file uses) after the given delay, plus a voice announcement."""
    def _fire():
        import time
        time.sleep(minutes * 60)
        if VOICE_OK:
            friday_speak(f"Boss — reminder: {text}")
        _log("FRIDAY", f"Reminder: {text}", "reminder")
        _push("FRIDAY Reminder", text)
    threading.Thread(target=_fire, daemon=True).start()



# ── Helpers ───────────────────────────────────────────────────────────────────

def _log(user: str, response: str, mode: str):
    EXCHANGE_LOG.append({
        "user": (user or "")[:200], "response": (response or "")[:200],
        "mode": mode, "ts": datetime.datetime.now().strftime("%H:%M:%S"),
    })


def safe(text: str) -> str:
    try:
        return str(text)[:500]
    except Exception:
        return "FRIDAY safe mode."


def emergency(prompt: str) -> str:
    p = (prompt or "").lower()
    if "time" in p:
        return datetime.datetime.now().strftime("%I:%M %p")
    if "date" in p:
        return datetime.datetime.now().strftime("%A, %B %d")
    return "I'm here, boss. Systems are limited right now."


def get_weather_brief() -> str:
    """wttr.in's plaintext format — free, no API key, no account."""
    try:
        import httpx
        r = httpx.get("https://wttr.in/?format=3", timeout=5)
        if r.status_code == 200:
            return r.text.strip()
    except Exception:
        pass
    return ""


def overall_status() -> str:
    if not friday_brain:
        return "EMERGENCY"
    brain_status = friday_brain.status()
    if not brain_status.get("groq") and not brain_status.get("anthropic"):
        return "NO-LLM"
    return "ONLINE"


__all__ = [
    "BASE_DIR",
    "BRAIN_OK",
    "CAPABILITIES_OK",
    "CAPABILITY_MAP",
    "CHECKIN_OK",
    "CONTACTS_OK",
    "CORE_STATUS",
    "EMOTIONAL_OK",
    "EXCHANGE_LOG",
    "HA_OK",
    "HEALTH_OK",
    "HUD_OK",
    "HULKBUSTER_OK",
    "LOCKDOWN_OK",
    "LOCKDOWN_TRIGGERS",
    "MEMORY_OK",
    "PROTOCOLS_OK",
    "RECON_OK",
    "RangeLevel",
    "SCATTER_OK",
    "SECURITY_OK",
    "TASKS_TABLE",
    "TASK_FILE",
    "TEAM_OK",
    "TRAINING_OK",
    "TRAINING_WHEELS_OK",
    "TRANSCRIBE_OK",
    "VERONICA_OK",
    "VOICE_OK",
    "WISDOM_OK",
    "WORKOUT_FILE",
    "WORKOUT_TABLE",
    "_FOCUS_SESSION",
    "_extract_topic",
    "_get_scatter_engine",
    "_log",
    "_push",
    "_read_local_tasks",
    "_read_local_workouts",
    "_write_local_tasks",
    "add_reminder",
    "add_task",
    "calibration",
    "career",
    "checkin_system",
    "complete_task",
    "continuity",
    "cross_check",
    "decisions",
    "drain_widgets",
    "emergency",
    "emotional_intel",
    "finance",
    "friday_brain",
    "friday_calendar",
    "friday_caps",
    "friday_code",
    "friday_contacts",
    "friday_gmail",
    "friday_health",
    "friday_protocols",
    "friday_recall",
    "friday_remember",
    "friday_security",
    "friday_speak",
    "friday_spotify",
    "friday_trainer",
    "friday_vision",
    "get_context_for",
    "get_emotional_trend",
    "get_mood_history",
    "get_profile",
    "get_recent_turns",
    "get_tasks",
    "get_weather_brief",
    "get_wisdom_context",
    "get_workouts",
    "goals",
    "habits",
    "hierarchical",
    "home_assistant",
    "hulkbuster",
    "journal",
    "legal",
    "log_emotion",
    "log_workout",
    "medicine_tracker",
    "news_anchor",
    "overall_status",
    "reading_mem",
    "recognizance",
    "relationships",
    "safe",
    "save_fact",
    "save_turn",
    "scatter_engine",
    "second_brain",
    "social",
    "spawn_widget",
    "suit_lockdown",
    "team",
    "training_wheels",
    "transcribe_audio",
    "translator",
    "tutor",
    "veronica",
    "voice_memory",
]
