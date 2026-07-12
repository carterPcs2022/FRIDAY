"""FRIDAY V2 — complete server. Flask + emotional intelligence + JARVIS
monitoring + green HUD + voice-mode control."""
import time
from flask import Flask, jsonify, redirect

# app + /health come before anything else that could fail to import or
# block — Railway's healthcheck needs a fast 200 from this path to keep
# the deploy alive at all, and gunicorn can't serve *any* route until
# this module finishes importing top to bottom. A single broken import
# further down (or in a nested core/ module) previously meant the whole
# app never came up, independent of how fast /health's own handler is.
app = Flask(__name__)
BOOT_TIME = time.time()


@app.route("/health")
def health():
    return "OK", 200


import os
import json
import datetime
import logging
import threading
from collections import deque
from pathlib import Path
from flask import request, send_file

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

EXCHANGE_LOG = deque(maxlen=10)
BASE_DIR = Path(__file__).resolve().parent

logging.basicConfig(level=logging.INFO, format='[FRIDAY] %(message)s')


def _ensure_memory():
    """Render's filesystem is ephemeral — a fresh deploy or cold start can
    land on a box with none of these directories. Most modules already
    mkdir(parents=True, exist_ok=True) their own path on first write, so
    this is mostly belt-and-suspenders for anything that assumes the
    directory is already there before its first write."""
    for name in ("memory", "logs", "static", "veronica_backups", "logs/backups"):
        try:
            (BASE_DIR / name).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logging.warning(f"Failed to ensure directory '{name}': {e}")


_ensure_memory()

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

# ── JARVIS monitoring ────────────────────────────────────────────────────────
JARVIS_URL = os.environ.get("JARVIS_URL", "http://localhost:8000")
JARVIS_TOKEN = os.environ.get("JARVIS_API_TOKEN", "")
JARVIS_ONLINE = False
COVERAGE_MODE = False

# ── Mayday ───────────────────────────────────────────────────────────────────
# "House party" per the boss's ask — checked verbatim (no fuzzy match) so an
# ordinary sentence that happens to mention a house party doesn't trip it.
MAYDAY_PHRASE = os.environ.get("MAYDAY_PHRASE", "house party").lower()
EMERGENCY_CONTACT_PHONE = os.environ.get("EMERGENCY_CONTACT_PHONE", "")


def _monitor_jarvis():
    """Single JARVIS health poll drives both the existing coverage-mode
    flag and (if available) friday_protocols' richer range level — a
    second independent poller would double the /health traffic and risk
    the two ever disagreeing about whether JARVIS is actually up."""
    global JARVIS_ONLINE, COVERAGE_MODE
    time.sleep(15)  # let this process's own /health start answering first
    while True:
        try:
            import requests as req
            r = req.get(f"{JARVIS_URL}/health", timeout=3)
            was_online = JARVIS_ONLINE
            JARVIS_ONLINE = r.status_code == 200
        except Exception:
            was_online = JARVIS_ONLINE
            JARVIS_ONLINE = False

        if PROTOCOLS_OK:
            friday_protocols.check_range(JARVIS_ONLINE)
            COVERAGE_MODE = friday_protocols.range_level != RangeLevel.FULL
        else:
            COVERAGE_MODE = not JARVIS_ONLINE

        if was_online and not JARVIS_ONLINE:
            logging.warning("JARVIS offline — FRIDAY assuming control")
            _log("SYSTEM", "JARVIS offline. FRIDAY is covering.", "coverage")
            _notify_jarvis_down()
        elif not was_online and JARVIS_ONLINE:
            logging.info("JARVIS back online — standing down")
            _log("SYSTEM", "JARVIS back online.", "handoff")
            if friday_brain:
                friday_brain.set_voice_mode("normal")
            if VOICE_OK:
                friday_speak("JARVIS is back online. Handing over, boss.", mode="normal")

        time.sleep(30)


def _notify_jarvis_down():
    pushover_user = os.environ.get("PUSHOVER_USER_KEY", "")
    pushover_token = os.environ.get("PUSHOVER_APP_TOKEN", "")
    if pushover_user and pushover_token:
        try:
            import requests as req
            req.post("https://api.pushover.net/1/messages.json", data={
                "token": pushover_token, "user": pushover_user,
                "title": "JARVIS Offline", "message": "FRIDAY has assumed control.",
                "priority": 1,
            }, timeout=5)
        except Exception:
            pass


def _start_thread(target, name: str):
    """A thread failing to spawn at all (e.g. a container thread/process
    ulimit some environments enforce more strictly than local dev does)
    must not be able to crash the whole module import — that would keep
    gunicorn from ever binding the port, taking /health down with it."""
    try:
        threading.Thread(target=target, daemon=True).start()
    except Exception as e:
        logging.warning(f"Failed to start {name} thread: {e}")


_start_thread(_monitor_jarvis, "JARVIS monitor")


def _startup_config_check():
    """Runs once, right after boot, so a misconfigured deploy pages the
    boss immediately instead of surfacing as a mystifying downstream
    failure hours later. Backgrounded like everything else here — /health
    must keep answering even if this (or the alert it sends) blows up."""
    try:
        from core.config_validator import check_and_alert
        result = check_and_alert()
        if not result["ok"]:
            logging.warning(f"Config check failed: {result['issues']}")
    except Exception as e:
        logging.warning(f"Config check failed to run: {e}")


_start_thread(_startup_config_check, "config check")

# ── Morning brief auto-trigger ───────────────────────────────────────────────
# Fires once a day at 8am local server time, so it happens even if nobody
# opens the HUD. A sleep-loop rather than the `schedule` package — one
# less dependency for something this simple.
#
# Combines news_anchor / relationships / second_brain in parallel — this
# is the "Protocol 20 MORNING" behavior from the spec, but there is no
# Protocol 20 (or 35 protocols at all) in core/friday_protocols.py; only
# 1-9 exist. Rather than fabricate a protocol number that isn't real, the
# combined-brief behavior is wired into this existing daily trigger.

_MORNING_BRIEF_HOUR = 8
_last_morning_brief_date = None

# Read by core/autonomous_agent.py's _alert() (imported at call time, not
# module load, to avoid a circular import) to hold non-urgent alerts
# during an active focus session.
_FOCUS_SESSION = {"active": False, "task": "", "end_time": 0}


def _combined_morning_brief() -> str:
    import concurrent.futures

    parts = {}

    def _news():
        if news_anchor:
            parts["news"] = news_anchor.morning_brief()

    def _people():
        if relationships:
            parts["relationships"] = relationships.relationship_brief()

    def _brain():
        if second_brain:
            parts["brain"] = second_brain.daily_digest()

    urgent_emails = []

    def _email():
        nonlocal urgent_emails
        if friday_gmail:
            urgent_emails = friday_gmail.get_urgent()

    energy = [""]

    def _energy():
        if voice_memory:
            energy[0] = voice_memory.predict_energy_now()

    todays_events = []
    calendar_connected = False

    def _calendar():
        nonlocal todays_events, calendar_connected
        if friday_calendar and friday_calendar.is_connected():
            calendar_connected = True
            todays_events = friday_calendar.get_today()

    followup = [""]

    def _followup():
        if continuity:
            followup[0] = continuity.generate_followup()

    goal_nudge = [""]

    def _goal_nudge_check():
        if goals:
            goal_nudge[0] = goals.nudge_neglected()

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(f) for f in
                  (_news, _people, _brain, _email, _energy, _calendar, _followup, _goal_nudge_check)]
        concurrent.futures.wait(futures, timeout=25)

    combined = "\n".join(f"- {v}" for v in parts.values() if v)

    from core.friday_memory import get_notes
    pending_tasks = [t for t in get_tasks() if not t.get("done")]
    recent_notes = get_notes(3)
    email_note = f"{len(urgent_emails)} urgent emails need attention." if urgent_emails else ""
    # Always an explicit status line — never leave calendar blank in the
    # prompt. An empty calendar_note gives the LLM zero signal about
    # *why* it's empty (not connected? connected but nothing today?), and
    # "combine these into one brief" style prompts otherwise happily fill
    # that gap with a plausible-sounding invented meeting.
    if not calendar_connected:
        calendar_note = "Calendar is not connected. Do not invent or assume any meetings, events, or appointments."
    elif not todays_events:
        calendar_note = "No events on calendar today. Do not invent any meetings."
    else:
        calendar_note = f"Today's calendar: {', '.join(e['title'] for e in todays_events[:5])}"

    extra = (
        f"Pending tasks: {len(pending_tasks)}\n"
        f"Recent notes: {[n['content'][:50] for n in recent_notes]}\n"
        f"{email_note}\n"
        f"{calendar_note}\n"
        f"{energy[0]}\n"
        f"Emotional followup needed: {followup[0]}\n"
        f"Goal reminder: {goal_nudge[0]}\n"
    )

    if (not combined and not pending_tasks and not recent_notes and not urgent_emails
            and not todays_events and not followup[0] and not goal_nudge[0]):
        return ""
    if not friday_brain:
        return combined

    result = friday_brain.think(
        f"Combine these into one morning brief for the boss:\n{combined}\n{extra}\n\n"
        f"News, relationships needing attention, tasks, and anything relevant "
        f"from stored knowledge. One flowing brief, not separate sections. "
        f"Under 80 words. FRIDAY style."
    )
    return result["response"]


def _morning_brief_loop():
    global _last_morning_brief_date
    time.sleep(30)  # let the rest of the module finish defining (_push, _log, etc.)
    while True:
        try:
            now = datetime.datetime.now()
            today = now.date().isoformat()
            if now.hour == _MORNING_BRIEF_HOUR and _last_morning_brief_date != today:
                _last_morning_brief_date = today
                response = safe(_combined_morning_brief())
                if not response and friday_brain:
                    result = friday_brain.think("FRIDAY run a morning brief")
                    response = safe(result.get("response", ""))
                if response:
                    save_turn("FRIDAY run a morning brief", response)
                    _log("FRIDAY run a morning brief", response, "morning-brief")
                    _push("Morning Brief", response)
                    if VOICE_OK and friday_brain:
                        friday_speak(response, mode=friday_brain.voice_mode)
        except Exception as e:
            logging.warning(f"Morning brief failed: {e}")
        time.sleep(1800)  # check twice an hour — plenty for an hour-granularity trigger


_start_thread(_morning_brief_loop, "morning brief")


def _start_autonomous():
    time.sleep(45)  # After health check passes
    try:
        from core.autonomous_agent import autonomous
        autonomous.start()
        print("[FRIDAY] Autonomous agent started")
    except Exception as e:
        print(f"[FRIDAY] Autonomous failed: {e}")


_start_thread(_start_autonomous, "autonomous agent")

# ── Proactive emotional check-ins ────────────────────────────────────────────
# core/emotional_intel.py's should_check_in() was defined but explicitly
# documented as unwired ("FRIDAY has no way to message first, only respond").
# This is that channel. Note get_emotional_trend()'s `days` parameter isn't
# actually implemented yet (see its docstring) — it returns the trend over
# the most recent 20 logged entries regardless of the value passed, not a
# true "last N days" window. That's fine at current log volume; noted here
# so it isn't mistaken for real date-filtering later.

_CHECKIN_INTERVAL = 4 * 3600
_LAST_CHECKIN_EMOTION = None


def _push(title: str, message: str, priority: int = 0):
    pushover_user = os.environ.get("PUSHOVER_USER_KEY", "")
    pushover_token = os.environ.get("PUSHOVER_APP_TOKEN", "")
    if not (pushover_user and pushover_token):
        return
    try:
        import requests as req
        req.post("https://api.pushover.net/1/messages.json", data={
            "token": pushover_token, "user": pushover_user,
            "title": title, "message": message, "priority": priority,
        }, timeout=5)
    except Exception:
        pass


# ── Assistant features: caller ID, notes, reminders, tasks ───────────────────

CALLER_TRIGGERS = [
    "incoming call from",
    "calling from",
    "call from",
    "who is calling",
    "who is this calling",
]

# "phone " and "ring " dropped from the source spec's list, and the
# literal "get [name] on the phone" removed entirely (that's a template
# placeholder, not real text — it can never match an actual prompt,
# since nobody types the literal string "[name]"). "phone "/"ring " are
# common enough in ordinary sentences ("phone battery is low", "the
# doorbell rang") that they'd regularly misfire — and unlike a
# false-positive task-list add, a misfire here returns action:"call" to
# whatever automation consumes it, i.e. a real attempted phone call to a
# garbled name, not just an odd chat reply. "call " stays: it's still
# broad, but it's also the one phrasing anyone will actually use to ask
# FRIDAY to call someone, and dropping it would break the feature's core
# use case.
CALL_TRIGGERS = [
    "call ", "dial ", "call up ", "give a call", "reach out to ",
]

# "what did i miss" moved to CATCHUP_TRIGGERS below — that feature's
# response already folds in unread email count alongside news/tasks/
# people, so it's a strict superset of what this email-only trigger
# would say for that exact phrase; keeping it in both lists would just
# mean this narrower one always wins (checked first) and the richer
# catch-up brief would never fire for it.
EMAIL_TRIGGERS = [
    "check my email", "what emails",
    "inbox", "any emails", "email summary",
    "unread emails", "check mail",
]

CATCHUP_TRIGGERS = [
    "what did i miss", "catch me up",
    "what happened", "what's new",
    "brief me", "status update",
    "bring me up to speed",
]

# "25 minutes" dropped — broad enough to match any sentence mentioning a
# duration for an unrelated reason ("the movie's 25 minutes long", "I'll
# be there in 25 minutes") and would start an actual focus session +
# background timer thread on a false match, not just an odd chat reply.
FOCUS_TRIGGERS = [
    "focus mode", "pomodoro", "focus session",
    "focus for", "work session",
    "do not disturb", "focus time",
]

HABIT_LOG_TRIGGERS = [
    "logged ", "did my ", "completed my",
    "finished my ", "i worked out",
    "i read ", "i meditated",
]

JOURNAL_TRIGGERS = [
    "log today", "journal entry",
    "diary", "log this",
    "today was", "how my day went",
]

PROBABILITY_TRIGGERS = [
    "what are the odds", "what are the chances",
    "probability", "likelihood",
    "will this work", "is this going to",
    "how likely", "odds of",
]

COMBAT_TRIGGERS = [
    "combat mode", "battle mode",
    "max efficiency", "terse mode",
    "crisis mode", "no fluff",
]

NORMAL_MODE_TRIGGERS = [
    "normal mode", "relax", "stand down",
    "at ease", "back to normal",
]

PRIORITY_TRIGGERS = [
    "what should i focus on", "what should i work on",
    "what's most important", "prioritize my day",
    "what do i do first", "help me prioritize",
    "what's the most important thing",
]

# "going to "/"i'm going to" dropped — far too broad ("I'm going to call
# Pepper", "I'm going to finish this later") and would fire a real web
# search + LLM call trying to extract a destination city from ordinary
# sentences that have nothing to do with travel.
TRAVEL_TRIGGERS = [
    "i'm traveling to", "traveling to",
    "trip to ", "flying to", "visiting ",
]

SPOTIFY_STOP_TRIGGERS = ["stop playing", "pause", "stop music", "no play"]
SPOTIFY_PLAY_TRIGGERS = ["play ", "now play", "put on", "friday play"]

CALENDAR_ADD_TRIGGERS = [
    "add to my calendar", "put on my calendar",
    "schedule a meeting", "add an event",
    "create an event", "book a meeting",
]

DRAFT_TRIGGERS = [
    "draft a reply", "reply to",
    "write a reply", "respond to",
    "draft email", "write email to",
]

# "inbox"/"what emails" (EMAIL_TRIGGERS) are substrings of "triage my
# inbox"/"organize my inbox"/"what emails need attention" — this list
# must be checked BEFORE EMAIL_TRIGGERS in command() or the narrower
# email-summary trigger always wins and smart triage never fires.
TRIAGE_TRIGGERS = [
    "triage my inbox", "sort my emails",
    "organize my inbox", "what emails need attention",
    "email categories", "sort emails",
]

# "i want to" dropped from the source spec's list — same reasoning as
# "need to" (TASK_ADD_TRIGGERS) and "going to " (TRAVEL_TRIGGERS): matches
# a huge share of ordinary sentences ("I want to eat lunch", "I want to
# know...") and would spin up a real LLM extraction call plus a new
# tracked goal on the false match.
GOAL_ADD_TRIGGERS = [
    "add goal", "new goal",
    "my goal is", "set a goal",
    "track my progress on",
]

GOAL_PROGRESS_TRIGGERS = [
    "worked on", "made progress on",
    "spent time on", "did work on",
    "progress update",
]

GOAL_REPORT_TRIGGERS = [
    "goal report", "how am i doing on",
    "progress report", "goals status",
    "what are my goals",
]

NOTE_TRIGGERS = [
    "note that", "make a note",
    "write that down", "remember that",
    "add to notes", "friday note",
    "jot that down",
]

REMINDER_TRIGGERS = [
    "remind me", "set a reminder",
    "don't let me forget", "alert me",
    "notify me",
]

# "need to" dropped from the source spec's list — it's broad enough to
# match a large share of ordinary conversation ("I need to know...", "you
# need to check...") and would silently misfile those as new tasks rather
# than answering the actual question. The rest are specific enough that
# false positives are rare.
TASK_ADD_TRIGGERS = [
    "add to my list", "add task",
    "todo:", "to do:",
    "don't forget to", "put on my list",
]

TASK_SHOW_TRIGGERS = [
    "what's on my list", "show my tasks",
    "what do i need to do", "my todo",
    "pending tasks", "what's pending",
]

# Deliberately not "intel on"/"scan for" — those are CAPABILITY_MAP's
# government_intel()/disaster_scan() (checked earlier in command()) and
# would shadow this if reused here.
RECON_TRIGGERS = [
    "run recon on", "recon on", "run recognizance on",
    "recognizance on", "scout ",
]

# "stand down" deliberately left out — NORMAL_MODE_TRIGGERS already owns
# that phrase for voice-mode reset, and SAFE_TRIGGERS is checked earlier
# in command() (right after Mayday), so reusing it here would shadow the
# existing normal-mode behavior for anyone who says it outside an
# emergency context.
SAFE_TRIGGERS = [
    "i'm safe", "i am safe", "all clear",
    "confirm safe", "safe now", "false alarm",
]

TASK_FILE = Path("memory/friday_tasks.json")
WORKOUT_FILE = Path("memory/friday_workouts.json")
BILLS_FILE = Path("memory/friday_bills.json")

HOMEKIT_TRIGGERS = {
    "turn off lights": "shortcuts run 'Lights Off'",
    "turn on lights": "shortcuts run 'Lights On'",
    "i'm leaving": "shortcuts run 'Leaving Home'",
    "i'm home": "shortcuts run 'Arriving Home'",
    "lock the door": "shortcuts run 'Lock Door'",
    "night mode": "shortcuts run 'Night Mode'",
}


def log_workout(workout_type: str, duration: int = 0):
    workouts = []
    if WORKOUT_FILE.exists():
        try:
            workouts = json.loads(WORKOUT_FILE.read_text())
        except Exception:
            workouts = []
    workouts.append({
        "type": workout_type, "duration": duration,
        "ts": datetime.datetime.now().isoformat(),
    })
    WORKOUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    WORKOUT_FILE.write_text(json.dumps(workouts[-365:], indent=2))


def get_tasks() -> list:
    if TASK_FILE.exists():
        try:
            return json.loads(TASK_FILE.read_text())
        except Exception:
            return []
    return []


def add_task(task: str, priority: str = "normal") -> dict:
    tasks = get_tasks()
    new_task = {
        "id": len(tasks) + 1, "task": task, "priority": priority,
        "done": False, "added": datetime.datetime.now().isoformat(),
    }
    tasks.append(new_task)
    TASK_FILE.parent.mkdir(parents=True, exist_ok=True)
    TASK_FILE.write_text(json.dumps(tasks, indent=2))
    return new_task


def complete_task(task_id: int):
    tasks = get_tasks()
    for t in tasks:
        if t.get("id") == task_id:
            t["done"] = True
            t["completed"] = datetime.datetime.now().isoformat()
    TASK_FILE.parent.mkdir(parents=True, exist_ok=True)
    TASK_FILE.write_text(json.dumps(tasks, indent=2))


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


def _proactive_checkin():
    global _LAST_CHECKIN_EMOTION
    if not (friday_brain and emotional_intel):
        return
    try:
        trend = get_emotional_trend()
        if not trend:
            return

        dominant = max(trend, key=trend.get)
        count = trend[dominant]

        # Don't re-send the same check-in every 4 hours if nothing's
        # changed since the last one — only fire on a fresh reading.
        if dominant == _LAST_CHECKIN_EMOTION:
            return

        if dominant in ("stressed", "sad", "frustrated") and count >= 3:
            result = friday_brain.think(
                f"The user has been {dominant} recently ({count} times in their "
                f"recent messages). As FRIDAY, proactively check in with one "
                f"warm, brief message. Not therapy. Just human. Under 20 words."
            )
            message = result.get("response", "")
            if not message:
                return

            _LAST_CHECKIN_EMOTION = dominant
            _log("SYSTEM", message, "proactive")
            _push("FRIDAY", message)
            if VOICE_OK:
                friday_speak(message, mode="support")
    except Exception as e:
        logging.warning(f"Proactive check-in failed: {e}")


def _schedule_checkins():
    while True:
        time.sleep(_CHECKIN_INTERVAL)
        _proactive_checkin()


_start_thread(_schedule_checkins, "check-in scheduler")

# ── JARVIS training sync ──────────────────────────────────────────────────────
# A plain sleep loop rather than pulling in the `schedule` package for one
# daily job — this codebase already uses this exact pattern for the JARVIS
# monitor and check-in threads above.
_DAILY_SYNC_INTERVAL = 24 * 3600


def _training_sync_loop():
    time.sleep(60)  # let the server finish booting first
    while True:
        try:
            if TRAINING_OK:
                friday_trainer.sync_from_jarvis()
        except Exception as e:
            logging.warning(f"JARVIS training sync failed: {e}")
        try:
            if PROTOCOLS_OK:
                friday_protocols.run_protocol(8)  # integrity check
                friday_protocols.run_protocol(9)  # budget alert
        except Exception as e:
            logging.warning(f"Daily protocol check failed: {e}")
        time.sleep(_DAILY_SYNC_INTERVAL)


if TRAINING_OK:
    _start_thread(_training_sync_loop, "training sync")

# ── Veronica (self-repair monitor) ────────────────────────────────────────────

def _veronica_startup():
    time.sleep(30)
    try:
        result = veronica.save_baselines()
        test = veronica.self_test()
        status = test.get("all_systems", "UNKNOWN")
        logging.info(f"Veronica online — {result['saved']} component(s) backed up, self-test: {status}")
    except Exception as e:
        logging.warning(f"Veronica startup failed: {e}")


def _veronica_monitor_loop():
    while True:
        time.sleep(300)
        try:
            veronica.monitor()
        except Exception as e:
            logging.warning(f"Veronica monitor failed: {e}")


if VERONICA_OK:
    _start_thread(_veronica_startup, "Veronica startup")
    _start_thread(_veronica_monitor_loop, "Veronica monitor")


def _sleep_adjustment():
    time.sleep(60)
    if not HEALTH_OK:
        return
    try:
        friday_health.adjust_friday_for_health()
        brief = friday_health.sleep_brief()
        if brief and VOICE_OK:
            friday_speak(brief)
    except Exception as e:
        logging.warning(f"Sleep adjustment failed: {e}")


if HEALTH_OK:
    _start_thread(_sleep_adjustment, "sleep adjustment")

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


# ── Health & status ───────────────────────────────────────────────────────────
# /health itself is registered at the very top of this file, before any of
# the imports below it that could fail.

@app.route("/")
def home():
    return jsonify({
        "status": "FRIDAY V2 ONLINE", "core": CORE_STATUS,
        "jarvis": "online" if JARVIS_ONLINE else "offline",
        "coverage": COVERAGE_MODE, "uptime": int(time.time() - BOOT_TIME),
    })


@app.route("/state")
def state():
    budget_info = {}
    try:
        import budget_2 as budget
        budget_info = budget.status()
    except Exception:
        pass

    emotional_trend = {}
    try:
        emotional_trend = get_emotional_trend()
    except Exception:
        pass

    # This process's own resource usage — not the user's device. psutil
    # running inside this server reports the server it's running on
    # (Render), never a locally-connected Mac/iPhone; labeling it
    # anything else would be actively misleading.
    cpu_pct = ram_pct = None
    try:
        import psutil
        cpu_pct = psutil.cpu_percent(interval=None)
        ram_pct = psutil.virtual_memory().percent
    except Exception:
        pass

    security = friday_security.get_threat_summary() if SECURITY_OK else {}
    uptime = int(time.time() - BOOT_TIME)

    return jsonify({
        "status": overall_status(), "core": CORE_STATUS,
        "jarvis_online": JARVIS_ONLINE, "coverage_mode": COVERAGE_MODE,
        "range_level": friday_protocols.range_level.value if PROTOCOLS_OK else "unknown",
        "training": friday_trainer.status() if TRAINING_OK else {},
        "budget": budget_info, "emotional_trend": emotional_trend,
        "cpu_pct": cpu_pct, "ram_pct": ram_pct, "security": security,
        "uptime_seconds": uptime, "uptime": uptime,
        "log": list(reversed(EXCHANGE_LOG)),
        "voice_mode": friday_brain.voice_mode if friday_brain else "normal",
    })


# Backward-compatible alias — the previous server.py exposed a /status route.
@app.route("/status")
def status_alias():
    return state()


# ── Main command endpoint ─────────────────────────────────────────────────────

@app.route("/command", methods=["POST"])
def command():
    prompt = ""
    try:
        data = request.get_json(silent=True) or {}
        prompt = data.get("prompt", "").strip()

        if not prompt:
            return jsonify({"response": "Say something, boss."})

        # ── Suit Lockdown — checked before EVERYTHING else, including Mayday.
        # While locked, the only thing this system will do with any message
        # is compare it to ENDGAME_PASSPHRASE — no trigger word, no prefix
        # stripping (see services/suit_lockdown.py's docstring for why that
        # used to be the actual bug). Anything else gets the same generic
        # "system locked" reply, so a stolen device can't fish for behavior
        # differences to guess the passphrase. ─────────────────────────────
        if LOCKDOWN_OK and suit_lockdown.is_locked():
            if suit_lockdown.try_unlock(prompt):
                response = "Unlocked. Welcome back, boss."
                _log(prompt, response, "lockdown_unlock")
                return jsonify({"response": response, "mode": "lockdown_unlock"})
            response = "System locked. Provide the passphrase to unlock."
            _log(prompt, response, "lockdown")
            return jsonify({"response": response, "mode": "lockdown", "blocked": True})

        LOCKDOWN_TRIGGERS = ["lockdown now", "emergency lockdown", "lock the system", "suit lockdown"]
        if LOCKDOWN_OK and any(t in prompt.lower() for t in LOCKDOWN_TRIGGERS):
            suit_lockdown.activate(reason="voice command")
            response = "Lockdown active. Standing by."
            _log(prompt, response, "lockdown_activate")
            return jsonify({"response": response, "mode": "lockdown_activate"})

        # ── Mayday — no LLM call, responds immediately ────────────────────────
        if MAYDAY_PHRASE in prompt.lower():
            response = "Mayday received. What's happening, boss?"
            _log(prompt, response, "MAYDAY")
            if friday_caps:
                friday_caps._pushover_alert(
                    "FRIDAY MAYDAY",
                    f"Mayday phrase triggered. Emergency contact on file: {EMERGENCY_CONTACT_PHONE}",
                )
            if CHECKIN_OK:
                try:
                    from services.checkin_system import emergency_pending
                    emergency_pending.set()
                except Exception:
                    pass
            audio_file = friday_speak(response) if VOICE_OK else None
            return jsonify({
                "response": response, "mode": "MAYDAY",
                "has_audio": bool(audio_file), "audio_file": audio_file,
            })

        # ── Safe check-in — no LLM call, stands down any pending escalation.
        # confirm_safe() already speaks its own line via friday_voice.speak()
        # (same as autonomous_agent._alert()'s convention of speaking
        # directly rather than through the HTTP response) so this doesn't
        # also generate a second, redundant audio_file for the HUD to play. ─
        if any(t in prompt.lower() for t in SAFE_TRIGGERS):
            response = "Good to hear, boss. Standing down." if CHECKIN_OK else "Glad to hear it, boss."
            if CHECKIN_OK:
                checkin_system.confirm_safe()
            _log(prompt, response, "safe_checkin")
            return jsonify({"response": response, "mode": "safe_checkin"})

        if SECURITY_OK:
            screen = friday_security.screen_request(friday_security.client_ip(request), prompt)
            if screen.get("blocked"):
                return jsonify({"response": "Request blocked.", "blocked": True}), 403

        # Learn from every request up front (not gated behind any one
        # response branch) so it applies regardless of which handler below
        # ends up serving it.
        try:
            if voice_memory:
                voice_memory.analyze_and_learn(prompt)
                best_mode = voice_memory.get_current_best_mode()
                if friday_brain and not COVERAGE_MODE:
                    friday_brain.set_voice_mode(best_mode)
        except Exception:
            pass

        # Dark mode — zero external connectivity, local-only responses
        if PROTOCOLS_OK and friday_protocols.range_level == RangeLevel.DARK:
            response = friday_protocols.emergency_response(prompt)
            _log(prompt, response, "emergency")
            return jsonify({"response": response, "mode": "emergency", "range": "dark"})

        # MCU capabilities — checked before the JARVIS proxy since these are
        # specifically FRIDAY's own named abilities, not generic chat that
        # should default to JARVIS when he's reachable.
        if CAPABILITIES_OK:
            p_lower = prompt.lower()
            for trigger, (handler, response_key) in CAPABILITY_MAP.items():
                if trigger in p_lower:
                    try:
                        result = handler(prompt)
                        response = result.get(response_key) or "Done, boss."
                        audio = friday_speak(response) if VOICE_OK else None
                        _log(prompt, response, trigger)
                        return jsonify({
                            "response": response, "mode": trigger,
                            "has_audio": bool(audio), "audio_file": audio,
                        })
                    except Exception as e:
                        logging.warning(f"Capability '{trigger}' failed: {e}")
                    break

        # Second-brain / news / relationships / code intents — same tier as
        # CAPABILITY_MAP above: FRIDAY's own named abilities, checked before
        # the JARVIS proxy for the same reason.
        p_lower = prompt.lower()

        if ("news" in p_lower or "what's happening" in p_lower) and news_anchor:
            response = news_anchor.morning_brief()
            _log(prompt, response, "news")
            return jsonify({"response": response, "mode": "news"})

        if "translate" in p_lower and translator:
            text = p_lower.replace("translate", "").replace("friday", "").strip()
            result = translator.translate(text)
            _log(prompt, result["translation"], "translate")
            return jsonify({"response": result["translation"], "mode": "translate"})

        if ("review this code" in p_lower or "fix this code" in p_lower) and friday_code:
            result = friday_code.quick_review(prompt)
            _log(prompt, result["review"], "code")
            return jsonify({"response": result["review"], "mode": "code"})

        if ("remember this" in p_lower or "store this" in p_lower) and second_brain:
            result = second_brain.ingest(prompt)
            response = f"Stored: {result['summary']}" if result["summary"] else "Stored, boss."
            _log(prompt, response, "brain")
            return jsonify({"response": response, "mode": "brain"})

        # "people brief on " — deliberately avoids the substring "intel on":
        # CAPABILITY_MAP already has an "intel on" trigger (government_intel(),
        # checked above this block) that matches as a substring anywhere in
        # the prompt, so any phrase containing "intel on" — even prefixed —
        # would still be unreachable.
        if "people brief on " in p_lower and relationships:
            name = p_lower.split("people brief on ")[-1].strip()
            result = relationships.get_intel(name)
            response = result.get("brief") or f"No intel on {name} yet, boss."
            _log(prompt, response, "intel")
            return jsonify({"response": response, "mode": "intel"})

        # ── Caller intelligence ──────────────────────────────────────────────
        if any(t in p_lower for t in CALLER_TRIGGERS):
            import re
            match = re.search(r"(?:call from|calling from|incoming call from)\s+(.+?)(?:\.|$)", p_lower)
            caller = match.group(1).strip().title() if match else ""

            if not caller:
                response = "Who's calling, boss?"
                _log(prompt, response, "caller_id")
                return jsonify({"response": response, "mode": "caller_id"})

            if relationships and friday_brain:
                intel = relationships.get_intel(caller)
                days_since = intel.get("days_since", -1)
                notes = intel.get("notes", [])
                context = f"Days since last contact: {days_since}\n" if days_since >= 0 else ""
                context += f"Notes: {notes[-1] if notes else 'None'}\n"
                context += f"Brief: {intel.get('brief', '')}"

                result = friday_brain.think(
                    f"Caller ID: {caller}\n{context}\n\n"
                    f"FRIDAY caller announcement. Who they are, last contact if "
                    f"known, answer or skip recommendation. Under 20 words. "
                    f"Natural. FRIDAY style."
                )
                response = result["response"] or f"It's {caller}, boss."
                _log(prompt, response, "caller_id")
                if VOICE_OK:
                    friday_speak(response)
                return jsonify({"response": response, "caller": caller, "mode": "caller_id"})

        # ── FRIDAY initiates a call ───────────────────────────────────────────
        if any(t in p_lower for t in CALL_TRIGGERS):
            import re
            match = re.search(
                r"(?:call|dial|call up|reach out to)\s+(.+?)(?:\s+(?:for|about|and|please|now).*)?$",
                p_lower
            )
            name = match.group(1).strip().title() if match else ""

            if not name:
                response = "Who do you want me to call, boss?"
                _log(prompt, response, "call")
                return jsonify({"response": response, "action": None})

            rel_intel = {}
            if relationships:
                rel_intel = relationships.get_intel(name)

            brief = ""
            if friday_brain:
                notes = rel_intel.get("notes", [])
                days = rel_intel.get("days_since", -1)
                brief_result = friday_brain.think(
                    f"Pre-call brief for calling {name}.\n"
                    f"Last contact: {days} days ago.\n"
                    f"Notes: {notes[-2:] if notes else 'None'}\n"
                    f"Context: {rel_intel.get('brief', '')}\n\n"
                    f"One sentence prep brief BEFORE the call. "
                    f"What to know going in. Under 15 words."
                )
                brief = brief_result["response"]

            response = f"Calling {name} now, boss. {brief}" if brief else f"Calling {name} now, boss."

            _log(prompt, response, "call")
            return jsonify({
                "response": response, "action": "call",
                "contact": name, "mode": "call_initiation",
            })

        # ── Catch-up brief ────────────────────────────────────────────────────
        if any(t in p_lower for t in CATCHUP_TRIGGERS) and friday_brain:
            import concurrent.futures

            catchup_data = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                futures = {}
                if friday_gmail:
                    futures[executor.submit(friday_gmail.get_unread, 10)] = "emails"
                if news_anchor:
                    futures[executor.submit(news_anchor.morning_brief)] = "news"
                if relationships:
                    futures[executor.submit(relationships.who_needs_attention)] = "people"

                catchup_data["tasks"] = len([t for t in get_tasks() if not t.get("done")])

                for f in concurrent.futures.as_completed(futures, timeout=15):
                    key = futures[f]
                    try:
                        catchup_data[key] = f.result()
                    except Exception:
                        pass

            emails = catchup_data.get("emails", [])
            news = catchup_data.get("news", "")
            people = catchup_data.get("people", [])
            tasks_cnt = catchup_data.get("tasks", 0)

            # This brief didn't pull calendar data before, but "brief" style
            # prompts can still volunteer a plausible-sounding meeting
            # unprompted — an explicit status line closes that gap the same
            # way _combined_morning_brief() needed it.
            if friday_calendar and friday_calendar.is_connected():
                todays = friday_calendar.get_today()
                calendar_line = (
                    f"Today's calendar: {', '.join(e['title'] for e in todays[:5])}"
                    if todays else "No events on calendar today. Do not invent any meetings."
                )
            else:
                calendar_line = "Calendar is not connected. Do not invent or assume any meetings, events, or appointments."

            result = friday_brain.think(
                f"Catch-up brief:\n"
                f"Unread emails: {len(emails)}\n"
                f"Top email: {emails[0].get('subject', '') if emails else 'none'}\n"
                f"Pending tasks: {tasks_cnt}\n"
                f"People needing contact: {len(people)}\n"
                f"News: {news[:100] if news else 'none'}\n"
                f"{calendar_line}\n\n"
                f"Quick catch-up brief. Most important first. Under 80 words. FRIDAY style."
            )
            response = result["response"]
            _log(prompt, response, "catchup")
            return jsonify({"response": response, "mode": "catchup"})

        # ── Focus / Pomodoro timer ────────────────────────────────────────────
        if any(t in p_lower for t in FOCUS_TRIGGERS):
            import re
            mins_match = re.search(r"(\d+)\s*min", p_lower)
            mins = int(mins_match.group(1)) if mins_match else 25

            task = "focus session"
            if friday_brain:
                result = friday_brain.think(
                    f"What task from this? '{prompt}'\n"
                    f"Reply with just the task or 'focus session'."
                )
                task = result["response"].strip() or "focus session"

            _FOCUS_SESSION["active"] = True
            _FOCUS_SESSION["task"] = task
            _FOCUS_SESSION["end_time"] = time.time() + mins * 60

            def _end_focus(mins=mins, task=task):
                time.sleep(mins * 60)
                _FOCUS_SESSION["active"] = False
                if VOICE_OK:
                    friday_speak(f"Focus session complete, boss. {mins} minutes done.")
                _push("FRIDAY", f"Focus session done: {task}")

            threading.Thread(target=_end_focus, daemon=True).start()

            response = f"Focus mode active, boss. {mins} minutes for: {task}. I'll hold non-urgent alerts."
            _log(prompt, response, "focus")
            return jsonify({"response": response, "mode": "focus"})

        # ── Habit logging ─────────────────────────────────────────────────────
        if any(t in p_lower for t in HABIT_LOG_TRIGGERS) and habits and friday_brain:
            result = friday_brain.think(f"Extract habit from: {prompt}\nOne word reply.")
            habit_name = result["response"].strip()
            if habit_name:
                log_result = habits.log(habit_name)
                streak = log_result.get("streak", 1)
                response = f"Logged {habit_name}, boss. That's a {streak}-day streak."
                _log(prompt, response, "habit")
                return jsonify({"response": response, "mode": "habit"})

        # ── Journal ───────────────────────────────────────────────────────────
        if any(t in p_lower for t in JOURNAL_TRIGGERS) and journal:
            mood = "neutral"
            if emotional_intel:
                mood = emotional_intel.analyze(prompt).get("emotion", "neutral")
            journal.log_entry(prompt, mood=mood)
            response = "Logged, boss."
            if friday_brain:
                result = friday_brain.think(
                    f"Acknowledge this journal entry warmly:\n{prompt}\n\nUnder 20 words. FRIDAY style."
                )
                response = result["response"] or response
            _log(prompt, response, "journal")
            return jsonify({"response": response, "mode": "journal"})

        # ── Probability assessment ────────────────────────────────────────────
        if any(t in p_lower for t in PROBABILITY_TRIGGERS) and friday_brain:
            result = friday_brain.think(
                f"Probability assessment:\n{prompt}\n\n"
                f"Analyze like FRIDAY in Civil War.\n"
                f"Give:\n1. Probability estimate (X%)\n2. Key factors for/against\n"
                f"3. What would change the odds\n4. Recommended action\n\n"
                f"You have no specific project data beyond what's in your actual "
                f"memory and second brain. If asked about project specifics "
                f"(manufacturing status, components, timelines) that you don't have "
                f"real logged information about, say so explicitly — do not invent "
                f"specific details, percentages, component names, or status updates "
                f"that aren't grounded in actual stored data. A probability estimate "
                f"itself is fine to give (that's the nature of the ask), but do NOT "
                f"list fake specific 'contributing factors' with fabricated precision "
                f"numbers unless those factors are real and known. FRIDAY tactical style."
            )
            response = result["response"]

            # Track the call for later calibration checking — best-effort:
            # a response that doesn't include a clean "X%" (rare, but the
            # LLM occasionally hedges instead) just isn't logged rather
            # than blocking the response on it.
            if calibration:
                try:
                    import re
                    pct_match = re.search(r"(\d{1,3})\s*%", response)
                    if pct_match:
                        calibration.log_prediction(prompt, int(pct_match.group(1)), reasoning=response)
                except Exception:
                    pass

            _log(prompt, response, "probability")
            return jsonify({"response": response, "mode": "probability"})

        # ── Recognizance ─────────────────────────────────────────────────────
        matched_recon = next((t for t in RECON_TRIGGERS if t in p_lower), None)
        if matched_recon and RECON_OK and friday_brain:
            # Case-insensitive strip of whichever trigger matched — p_lower
            # already told us it's in there somewhere.
            idx = p_lower.find(matched_recon)
            situation = (prompt[:idx] + prompt[idx + len(matched_recon):]).strip() if idx >= 0 else prompt
            result = recognizance.scout(situation or prompt)
            response = result.get("brief") or "Nothing solid to report, boss."
            _log(prompt, response, "recon")
            audio_file = friday_speak(response) if VOICE_OK else None
            return jsonify({
                "response": response, "mode": "recon",
                "has_audio": bool(audio_file), "audio_file": audio_file,
            })

        # ── System doctor ────────────────────────────────────────────────────
        DIAGNOSTICS_TRIGGERS = ["run diagnostics"]
        if any(t in p_lower for t in DIAGNOSTICS_TRIGGERS):
            from services import system_doctor
            report = system_doctor.full_check()
            response = "Health check unavailable, boss."
            if friday_brain:
                result = friday_brain.think(
                    f"Summarize this system health check for the boss, naturally, "
                    f"not as raw data. One or two sentences, FRIDAY style:\n{report}"
                )
                response = result.get("response", response)
            _log(prompt, response, "diagnostics")
            audio_file = friday_speak(response) if VOICE_OK else None
            return jsonify({
                "response": response, "mode": "diagnostics",
                "has_audio": bool(audio_file), "audio_file": audio_file,
            })

        # ── Cross-check with JARVIS ────────────────────────────────────────────
        CROSS_CHECK_TRIGGERS = [
            "check with jarvis", "cross check", "ask jarvis too",
            "get a second opinion", "what does jarvis think",
        ]
        matched_trigger = next((t for t in CROSS_CHECK_TRIGGERS if t in p_lower), None)
        if matched_trigger and cross_check:
            question = prompt
            for t in CROSS_CHECK_TRIGGERS:
                question = question.lower().replace(t, "").strip()
            question = question or prompt

            result = cross_check.ask_both(question)
            friday_side = result["friday"][:150]
            jarvis_side = result["jarvis"][:150]
            if result["agreement"]["aligned"]:
                response = (
                    f"We're aligned, boss. Me: \"{friday_side}\" "
                    f"JARVIS: \"{jarvis_side}\""
                )
            else:
                response = (
                    f"We don't agree on this one, boss. Me: \"{friday_side}\" "
                    f"JARVIS: \"{jarvis_side}\""
                )
            _log(prompt, response, "cross_check")
            return jsonify({"response": response, "mode": "cross_check", "detail": result})

        # ── Combat / normal mode ──────────────────────────────────────────────
        if any(t in p_lower for t in COMBAT_TRIGGERS) and friday_brain:
            friday_brain.set_voice_mode("combat")
            response = "Combat mode. Standing by."
            _log(prompt, response, "mode")
            return jsonify({"response": response, "mode": "combat"})

        if any(t in p_lower for t in NORMAL_MODE_TRIGGERS) and friday_brain:
            friday_brain.set_voice_mode("normal")
            response = "Standing down, boss."
            _log(prompt, response, "mode")
            return jsonify({"response": response, "mode": "normal"})

        # ── Priority focus ────────────────────────────────────────────────────
        if any(t in p_lower for t in PRIORITY_TRIGGERS) and friday_brain:
            pending = [t for t in get_tasks() if not t.get("done")]
            emails = []
            if friday_gmail:
                try:
                    emails = friday_gmail.get_urgent()
                except Exception:
                    pass

            notes_ctx = ""
            if second_brain:
                actions = second_brain.get_actions()
                if actions:
                    notes_ctx = "\n".join(a.get("action", "") for a in actions[:3])

            energy = voice_memory.predict_energy_now() if voice_memory else ""

            result = friday_brain.think(
                f"Priority analysis — what should boss focus on NOW:\n\n"
                f"Pending tasks ({len(pending)}):\n"
                + "\n".join(f"- {t['task']}" for t in pending[:5])
                + f"\n\nUrgent emails: {len(emails)}\n"
                f"Pending actions from notes: {notes_ctx}\n"
                f"Energy read: {energy}\n\n"
                f"What's the single most important thing to do right now?\n"
                f"Then the next 2 things. Be specific and decisive.\n"
                f"Under 60 words. FRIDAY tactical style."
            )
            response = result["response"]
            _log(prompt, response, "priority")
            return jsonify({"response": response, "mode": "priority"})

        # ── Travel intel ──────────────────────────────────────────────────────
        if any(t in p_lower for t in TRAVEL_TRIGGERS) and friday_brain:
            import re
            match = re.search(
                r"(?:traveling to|trip to|flying to|visiting)\s+(.+?)(?:\s+(?:for|on|next|this).*)?$",
                p_lower
            )
            city = match.group(1).strip().title() if match else ""

            if city:
                from core.tools.web import search
                results = search(f"{city} travel tips time zone weather", 3)
                result = friday_brain.think(
                    f"Travel intel for {city}:\n\n"
                    + "\n".join(
                        f"- {r.get('title', '')}: {r.get('snippet', '')[:100]}"
                        for r in results[:3]
                    )
                    + "\n\nBrief travel brief:\n"
                      "1. Current time and time zone difference from New York\n"
                      "2. Current weather\n3. 2-3 things to know\nUnder 60 words. FRIDAY style."
                )
                response = result["response"]
                _log(prompt, response, "travel")
                return jsonify({"response": response, "mode": "travel"})

        # ── Spotify direct control ────────────────────────────────────────────
        if any(t in p_lower for t in SPOTIFY_STOP_TRIGGERS) and friday_spotify:
            friday_spotify.pause()
            response = "Pausing, boss."
            _log(prompt, response, "spotify")
            return jsonify({"response": response, "mode": "spotify"})

        for trigger in SPOTIFY_PLAY_TRIGGERS:
            if trigger in p_lower and friday_spotify:
                query = p_lower.split(trigger)[-1].strip().replace("on spotify", "").strip()
                result = friday_spotify.play(query)
                if result.get("playing"):
                    response = f"Playing {result.get('track', '')} by {result.get('artist', '')}, boss."
                else:
                    response = result.get("error", "Couldn't play that, boss.")
                _log(prompt, response, "spotify")
                return jsonify({"response": response, "mode": "spotify"})

        # ── Calendar: create an event ─────────────────────────────────────────
        if any(t in p_lower for t in CALENDAR_ADD_TRIGGERS) and friday_brain:
            if not (friday_calendar and friday_calendar.is_connected()):
                response = "Your calendar isn't connected yet, boss."
                _log(prompt, response, "calendar")
                return jsonify({"response": response, "mode": "calendar"})

            import re as rex
            result = friday_brain.think(
                f"Extract a calendar event from: {prompt}\n"
                f"Current time: {datetime.datetime.now().isoformat()}\n\n"
                f'Reply as JSON: {{"title": str, "start": "ISO 8601 datetime", '
                f'"end": "ISO 8601 datetime"}}\n'
                f"If no duration is given, default to 30 minutes. JSON only."
            )
            try:
                clean = rex.sub(r"```json|```", "", result["response"]).strip()
                data = json.loads(clean)
                created = friday_calendar.create_event(
                    data.get("title", "Event"), data["start"], data["end"]
                )
                if created.get("ok"):
                    response = f"Added \"{data.get('title', 'Event')}\" to your calendar, boss."
                else:
                    response = created.get("error", "Couldn't add that to your calendar, boss.")
            except Exception:
                response = "Wasn't sure what to schedule there, boss — try again with a time?"
            _log(prompt, response, "calendar")
            return jsonify({"response": response, "mode": "calendar"})

        # ── Goals ─────────────────────────────────────────────────────────────
        if any(t in p_lower for t in GOAL_REPORT_TRIGGERS) and goals:
            active = goals.get_active_goals()
            if not active:
                response = "No goals tracked yet, boss. Tell me your goals and I'll track them."
            elif friday_brain:
                result = friday_brain.think(
                    f"Quick goal status for {len(active)} active goals:\n"
                    + "\n".join(
                        f"- {g['name']}: {g.get('sessions', 0)} sessions, "
                        f"last worked {(g.get('last_worked') or 'never')[:10]}"
                        for g in active
                    )
                    + "\n\nBrief status. Under 40 words. FRIDAY style."
                )
                response = result["response"]
            else:
                response = f"{len(active)} active goals, boss."
            _log(prompt, response, "goal_report")
            return jsonify({"response": response, "mode": "goal_report"})

        if any(t in p_lower for t in GOAL_ADD_TRIGGERS) and goals and friday_brain:
            import re as rex
            extract = friday_brain.think(
                f"Extract goal from: '{prompt}'\n"
                f'Reply as JSON: {{"name": str, "description": str}}'
            )
            try:
                clean = rex.sub(r"```json|```", "", extract["response"]).strip()
                data = json.loads(clean)
                name = data.get("name", "")
                if name:
                    goals.add_goal(name, data.get("description", ""))
                    response = f"Goal added, boss: {name}. I'll track your progress."
                else:
                    response = "What's the goal, boss?"
            except Exception:
                response = "What's the goal, boss?"
            _log(prompt, response, "goal_add")
            return jsonify({"response": response, "mode": "goal_add"})

        # Left out of the source spec's command() wiring entirely (the
        # trigger list was declared but never actually checked) — without
        # this, "worked on X" would never log progress, which defeats the
        # whole point of tracking goals automatically.
        if any(t in p_lower for t in GOAL_PROGRESS_TRIGGERS) and goals:
            log_result = goals.log_progress(work_done=prompt, auto_detect=True)
            if log_result.get("logged"):
                response = f"Logged progress on {log_result['goal']}, boss. Session {log_result['sessions']}."
            else:
                response = "Noted — didn't match it to a tracked goal, boss."
            _log(prompt, response, "goal_progress")
            return jsonify({"response": response, "mode": "goal_progress"})

        # ── Email: draft / triage (checked before EMAIL_TRIGGERS — that
        # list's bare "inbox"/"what emails" are substrings of these
        # phrases and would otherwise always win first) ────────────────────
        if any(t in p_lower for t in DRAFT_TRIGGERS) and friday_gmail and friday_brain:
            import re as rex
            extract = friday_brain.think(
                f"From this: '{prompt}'\n"
                f"Extract: who to reply to and what to say.\n"
                f'JSON: {{"to": str, "instruction": str}}'
            )
            try:
                clean = rex.sub(r"```json|```", "", extract["response"]).strip()
                data = json.loads(clean)
                search = data.get("to", "")
                instruction = data.get("instruction", "")
            except Exception:
                search, instruction = prompt, ""

            found = friday_gmail.find_email(search)
            if found:
                draft_result = friday_gmail.draft_reply(
                    email_subject=found.get("subject", ""), email_from=found.get("from", ""),
                    email_body=found.get("body", ""), instruction=instruction,
                )
                draft = draft_result.get("draft", "")
                response = (
                    f"Here's a draft reply to {found.get('from', '')[:30]}, boss:\n\n"
                    f"{draft}\n\nWant me to send it or adjust anything?"
                )
            else:
                response = "I couldn't find that email, boss. Try 'FRIDAY draft a reply to [exact name or subject]'."
            _log(prompt, response, "email_draft")
            return jsonify({"response": response, "mode": "email_draft"})

        if any(t in p_lower for t in TRIAGE_TRIGGERS) and friday_gmail:
            triage = friday_gmail.smart_triage()
            summary = triage.get("summary", "")
            cats = triage.get("categories", {})
            urgent = cats.get("urgent", [])
            response = (
                f"Inbox triage complete, boss. {summary}.\n"
                f"Urgent: {', '.join(urgent[:2]) if urgent else 'none'}."
            )
            _log(prompt, response, "email_triage")
            return jsonify({"response": response, "triage": triage, "mode": "email_triage"})

        # ── Email ─────────────────────────────────────────────────────────────
        if any(t in p_lower for t in EMAIL_TRIGGERS) and friday_gmail:
            summary = friday_gmail.summarize_inbox()
            _log(prompt, summary, "email")
            return jsonify({"response": summary, "mode": "email"})

        # ── Note that ─────────────────────────────────────────────────────────
        if any(t in p_lower for t in NOTE_TRIGGERS):
            from core.friday_memory import save_note, get_recent_turns
            turns = get_recent_turns(2)
            note = {
                "ts": datetime.datetime.now().isoformat(),
                "content": turns[-1].get("friday", "") if turns else prompt,
                "context": prompt,
            }
            save_note(note)
            response = "Noted, boss."
            _log(prompt, response, "note")
            return jsonify({"response": response, "mode": "note"})

        # ── Reminders ─────────────────────────────────────────────────────────
        if any(t in p_lower for t in REMINDER_TRIGGERS) and friday_brain:
            import re as rex
            result = friday_brain.think(
                f"Extract reminder from: {prompt}\n\n"
                f"Reply as JSON: {{\"task\": str, \"minutes\": int}}\n"
                f"Examples:\n"
                f"'remind me in 30 minutes to call back' -> {{\"task\":\"call back\",\"minutes\":30}}\n"
                f"'remind me at 3pm' -> {{\"task\":\"reminder\",\"minutes\": calculated from now}}\n"
                f"JSON only."
            )["response"]
            try:
                clean = rex.sub(r"```json|```", "", result).strip()
                data = json.loads(clean)
                task = data.get("task", "reminder")
                mins = int(data.get("minutes", 5))
                add_reminder(task, mins)
                response = f"Reminder set for {mins} minutes, boss. I'll let you know."
            except Exception:
                response = "What do you need reminding about, boss?"
            _log(prompt, response, "reminder")
            return jsonify({"response": response, "mode": "reminder"})

        # ── Task list ─────────────────────────────────────────────────────────
        if any(t in p_lower for t in TASK_SHOW_TRIGGERS):
            tasks = [t for t in get_tasks() if not t.get("done")]
            if not tasks:
                response = "Nothing on the list, boss. Clear schedule."
            elif friday_brain:
                result = friday_brain.think(
                    f"Task list summary:\n"
                    + "\n".join(f"- {t['task']}" for t in tasks[:10])
                    + "\n\nBrief summary. What needs attention first. Under 40 words."
                )
                response = result["response"]
            else:
                response = f"{len(tasks)} things on your list, boss."
            _log(prompt, response, "tasks")
            return jsonify({"response": response, "mode": "tasks"})

        if any(t in p_lower for t in TASK_ADD_TRIGGERS) and friday_brain:
            result = friday_brain.think(
                f"Extract task from: {prompt}\n"
                f"Reply with just the task. No extra text."
            )["response"]
            task = result.strip()
            if task:
                add_task(task)
                response = f"Added to your list, boss: {task}"
            else:
                response = "What do you want to add, boss?"
            _log(prompt, response, "task_add")
            return jsonify({"response": response, "mode": "task_add"})

        # ── Smart home via HomeKit (Shortcuts run on the Mac Bridge) ──────────
        for trigger, shortcut in HOMEKIT_TRIGGERS.items():
            if trigger in p_lower:
                if TRAINING_WHEELS_OK and not training_wheels.can_perform("mac_bridge_control"):
                    response = "Not authorized yet, boss — trust score isn't there for Mac Bridge control."
                    _log(prompt, response, "homekit")
                    return jsonify({"response": response, "mode": "homekit", "blocked": True})

                mac_url = os.environ.get("MAC_BRIDGE_URL", "")
                if not mac_url:
                    response = "Mac bridge isn't configured, boss."
                else:
                    try:
                        import requests as req
                        r = req.post(f"{mac_url}/mac/run",
                                    json={"command": shortcut, "token": os.environ.get("MAC_BRIDGE_TOKEN", "")},
                                    timeout=5)
                        ok = r.status_code == 200 and not r.json().get("error")
                        response = "Done, boss." if ok else "Couldn't reach the Mac bridge, boss."
                    except Exception:
                        ok = False
                        response = "Couldn't reach the Mac bridge, boss."
                    if TRAINING_WHEELS_OK:
                        training_wheels.record_outcome("mac_bridge_control", ok)
                _log(prompt, response, "homekit")
                return jsonify({"response": response, "mode": "homekit"})

        # ── Open a Mac app via Mac Bridge ──────────────────────────────────────
        MAC_APP_TRIGGERS = {
            "open spotify": "Spotify", "open chrome": "Google Chrome",
            "open safari": "Safari", "open terminal": "Terminal",
            "open finder": "Finder", "open notes": "Notes",
        }
        for trigger, app_name in MAC_APP_TRIGGERS.items():
            if trigger in p_lower:
                if TRAINING_WHEELS_OK and not training_wheels.can_perform("mac_bridge_control"):
                    response = "Not authorized yet, boss — trust score isn't there for Mac Bridge control."
                    _log(prompt, response, "mac_bridge")
                    return jsonify({"response": response, "mode": "mac_bridge", "blocked": True})

                from services.mac_bridge import mac_bridge
                result = mac_bridge.open_app(app_name)
                ok = "error" not in result
                response = f"Done, boss. {app_name} is opening." if ok else f"Couldn't reach your Mac, boss: {result['error']}"
                if TRAINING_WHEELS_OK:
                    training_wheels.record_outcome("mac_bridge_control", ok)
                _log(prompt, response, "mac_bridge")
                return jsonify({"response": response, "mode": "mac_bridge"})

        # Proxy to JARVIS if online and not in coverage mode
        if JARVIS_ONLINE and not COVERAGE_MODE:
            try:
                import requests as req
                r = req.post(
                    f"{JARVIS_URL}/stark/chat", json={"message": prompt},
                    headers={"Authorization": f"Bearer {JARVIS_TOKEN}"}, timeout=10,
                )
                if r.status_code == 200:
                    response = r.json().get("response", "")
                    _log(prompt, response, "jarvis-proxy")
                    return jsonify({"response": safe(response), "mode": "jarvis", "via": "proxy"})
            except Exception:
                pass

        # FRIDAY handles it herself
        if friday_brain:
            try:
                emotion_data = {}
                if emotional_intel:
                    emotion_data = emotional_intel.analyze(prompt)
                    if emotion_data.get("emotion") != "neutral":
                        log_emotion(emotion_data["emotion"], emotion_data["intensity"], prompt)
                        try:
                            if continuity and emotion_data.get("intensity", 0) >= 4:
                                continuity.record_session(
                                    emotion=emotion_data.get("emotion", "neutral"),
                                    intensity=emotion_data.get("intensity", 0),
                                    context=prompt[:200], topic=_extract_topic(prompt),
                                )
                        except Exception:
                            pass

                context = get_context_for(prompt)
                if TRAINING_OK:
                    knowledge = friday_trainer.get_context_brief(prompt)
                    if knowledge:
                        context = "\n".join(filter(None, [knowledge, context]))

                if COVERAGE_MODE:
                    friday_brain.set_voice_mode("coverage")

                result = friday_brain.think(
                    prompt, context=context, emotion_context=emotion_data.get("system_note", ""),
                )
                response = result["response"]

                if (emotional_intel and emotion_data.get("should_acknowledge")
                        and emotion_data.get("response_guidance")):
                    prefix = emotional_intel.generate_emotional_response_prefix(
                        emotion_data["emotion"], emotion_data["intensity"],
                    )
                    if prefix and not response.startswith(prefix):
                        response = prefix + response

                clean = safe(response)
                save_turn(prompt, clean)
                _log(prompt, clean, "friday-coverage" if COVERAGE_MODE else "friday")

                audio_file = friday_speak(clean, mode=friday_brain.voice_mode) if VOICE_OK else None

                return jsonify({
                    "response": clean, "mode": "friday", "model": result.get("model", ""),
                    "ms": result.get("ms", 0), "emotion": emotion_data.get("emotion", "neutral"),
                    "covering": COVERAGE_MODE,
                    "has_audio": bool(audio_file), "audio_file": audio_file,
                })
            except Exception as e:
                logging.error(f"Brain error: {e}")

        response = emergency(prompt)
        _log(prompt, response, "emergency")
        return jsonify({"response": response, "mode": "emergency"})

    except Exception:
        return jsonify({"response": "I'm here, boss. Give me a moment.", "mode": "critical"}), 200


@app.route("/chat", methods=["POST"])
def chat():
    """Alias for /command."""
    return command()


@app.route("/friday/ask", methods=["POST"])
def friday_ask():
    """Thin alias for iOS Shortcuts — accepts {"message": ...} instead of
    {"prompt": ...} so a Shortcut can be wired up without reshaping its
    dictated-text payload."""
    data = request.get_json(silent=True) or {}
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"response": "Didn't catch that, boss."})
    with app.test_request_context("/command", method="POST", json={"prompt": message}):
        return command()


@app.route("/friday/vision/analyze", methods=["POST"])
def friday_vision_analyze():
    """Paperclip-button endpoint — the HUD base64-encodes the image
    client-side (see uploadVisionImage() in the page script below) and
    posts it here rather than a multipart upload, since the payload is
    small (single frame, not video) and JSON keeps this symmetrical with
    every other route on this server."""
    if not friday_vision:
        return jsonify({"error": "Vision isn't available, boss."}), 503
    data = request.get_json(silent=True) or {}
    image_b64 = data.get("image", "")
    question = data.get("question", "")
    if not image_b64:
        return jsonify({"error": "No image provided."}), 400
    result = friday_vision.analyze(image_b64, question)
    _log(question or "[image]", result.get("analysis", result.get("error", "")), "vision")
    return jsonify(result)


@app.route("/friday/calibration/score")
def friday_calibration_score():
    if not calibration:
        return jsonify({"error": "Calibration tracking isn't available, boss."}), 503
    return jsonify(calibration.calibration_score())


@app.route("/friday/calibration/resolve", methods=["POST"])
def friday_calibration_resolve():
    if not calibration:
        return jsonify({"error": "Calibration tracking isn't available, boss."}), 503
    data = request.get_json(silent=True) or {}
    pred_id = data.get("id", "")
    outcome = data.get("outcome")
    if not pred_id or outcome is None:
        return jsonify({"error": "id and outcome are required"}), 400
    return jsonify(calibration.resolve_prediction(pred_id, bool(outcome)))


@app.route("/friday/voice/audio")
def friday_voice_audio():
    """Serve a generated voice clip. Every generation has a unique
    filename already (see services/friday_voice.py), and this endpoint
    also sends no-cache headers as a second layer against any client or
    proxy that caches by URL regardless."""
    filename = request.args.get("file", "")
    if not filename:
        return jsonify({"error": "file required"}), 400

    path = BASE_DIR / "static" / filename
    if ".." in filename or not path.resolve().is_relative_to(BASE_DIR / "static"):
        return jsonify({"error": "invalid file"}), 400
    if not path.exists():
        return jsonify({"error": "not found"}), 404

    response = send_file(str(path), mimetype="audio/mpeg")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/friday/voice/transcribe", methods=["POST"])
def friday_voice_transcribe():
    """Hands-free command capture: the HUD records after hearing the wake
    word and posts the clip here rather than doing STT in-browser, since
    Web Speech API recognition quality/availability varies a lot by
    browser — a single server-side Whisper call is consistent everywhere."""
    if not TRANSCRIBE_OK:
        return jsonify({"text": "", "error": "Transcription isn't available, boss."}), 503
    if "audio" not in request.files:
        return jsonify({"text": "", "error": "audio file required"}), 400

    audio_file = request.files["audio"]
    audio_bytes = audio_file.read()
    filename = audio_file.filename or "audio.webm"

    # Speaker-verify before spending a Groq Whisper call — only skip
    # transcription on a *confirmed* mismatch (verified=True, match=False);
    # any other outcome (not enrolled, bridge unreachable, internal error)
    # fails open exactly like bridge.py's own /voice/verify does.
    mac_url = os.environ.get("MAC_BRIDGE_URL", "")
    if mac_url:
        try:
            import httpx
            r = httpx.post(
                f"{mac_url}/voice/verify",
                files={"audio": (filename, audio_bytes, audio_file.mimetype or "audio/webm")},
                data={"profile": "default"},
                headers={"Authorization": f"Bearer {os.environ.get('MAC_BRIDGE_TOKEN', '')}"},
                timeout=10,
            )
            verify_result = r.json()
            if verify_result.get("verified") is True and verify_result.get("match") is False:
                return jsonify({
                    "text": "", "rejected": True, "reason": "voice_mismatch",
                    "score": verify_result.get("score"),
                })
        except Exception:
            pass

    result = transcribe_audio(audio_bytes, filename=filename)
    return jsonify(result)


@app.route("/friday/voice/enroll", methods=["POST"])
def friday_voice_enroll():
    """Thin proxy to Mac Bridge's /voice/enroll — the browser never sees
    MAC_BRIDGE_TOKEN, so enrollment has to go through here rather than the
    HUD hitting the bridge directly."""
    mac_url = os.environ.get("MAC_BRIDGE_URL", "")
    if not mac_url:
        return jsonify({"error": "Mac Bridge not configured"}), 503
    if "audio" not in request.files:
        return jsonify({"error": "audio file required"}), 400

    audio_file = request.files["audio"]
    profile = request.form.get("profile", "default")
    try:
        import httpx
        r = httpx.post(
            f"{mac_url}/voice/enroll",
            files={"audio": (audio_file.filename or "audio.webm", audio_file.read(), audio_file.mimetype or "audio/webm")},
            data={"profile": profile},
            headers={"Authorization": f"Bearer {os.environ.get('MAC_BRIDGE_TOKEN', '')}"},
            timeout=15,
        )
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"error": f"Couldn't reach the Mac bridge, boss: {e}"}), 502


@app.route("/friday/voice/profile/status", methods=["GET"])
def friday_voice_profile_status():
    """Thin proxy to Mac Bridge's /voice/profile/status — same token-hiding
    rationale as friday_voice_enroll above."""
    mac_url = os.environ.get("MAC_BRIDGE_URL", "")
    if not mac_url:
        return jsonify({"error": "Mac Bridge not configured"}), 503

    profile = request.args.get("profile", "default")
    try:
        import httpx
        r = httpx.get(
            f"{mac_url}/voice/profile/status",
            params={"profile": profile},
            headers={"Authorization": f"Bearer {os.environ.get('MAC_BRIDGE_TOKEN', '')}"},
            timeout=10,
        )
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"error": f"Couldn't reach the Mac bridge, boss: {e}"}), 502


@app.route("/friday/voice/reset", methods=["POST"])
def friday_voice_reset():
    """Thin proxy to Mac Bridge's /voice/reset — deletes the stored voice
    profile so a polluted enrollment (bad/partial samples) can be cleared
    and re-enrolled from scratch without SSHing in to rm the file."""
    mac_url = os.environ.get("MAC_BRIDGE_URL", "")
    if not mac_url:
        return jsonify({"error": "Mac Bridge not configured"}), 503

    profile = (request.get_json(silent=True) or {}).get("profile", "default")
    try:
        import httpx
        r = httpx.post(
            f"{mac_url}/voice/reset",
            data={"profile": profile},
            headers={"Authorization": f"Bearer {os.environ.get('MAC_BRIDGE_TOKEN', '')}"},
            timeout=10,
        )
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"error": f"Couldn't reach the Mac bridge, boss: {e}"}), 502


# ── JARVIS takeover ────────────────────────────────────────────────────────────

@app.route("/takeover", methods=["POST"])
def takeover():
    """JARVIS calls this when it intentionally shuts down."""
    global COVERAGE_MODE
    COVERAGE_MODE = True
    data = request.get_json(silent=True) or {}
    reason = data.get("reason", "JARVIS shutdown")
    logging.info(f"Takeover received: {reason}")
    _log("SYSTEM", f"FRIDAY assuming control: {reason}", "takeover")
    return jsonify({"status": "coverage_active", "reason": reason})


# ── Voice mode control ─────────────────────────────────────────────────────────

@app.route("/mode", methods=["POST"])
def set_mode():
    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "normal")
    if friday_brain:
        friday_brain.set_voice_mode(mode)
    return jsonify({"mode": mode, "status": "set"})


# ── Range protocols ────────────────────────────────────────────────────────────

@app.route("/friday/protocols")
def list_protocols():
    if not PROTOCOLS_OK:
        return jsonify({"error": "protocols unavailable"}), 503
    from core.friday_protocols import FRIDAY_PROTOCOLS
    return jsonify({"protocols": FRIDAY_PROTOCOLS, "current_range": friday_protocols.range_level.value})


@app.route("/friday/protocols/<int:n>", methods=["POST"])
def run_protocol(n):
    if not PROTOCOLS_OK:
        return jsonify({"error": "protocols unavailable"}), 503
    return jsonify(friday_protocols.run_protocol(n))


@app.route("/friday/range")
def range_status():
    if not PROTOCOLS_OK:
        return jsonify({"error": "protocols unavailable"}), 503
    return jsonify(friday_protocols.get_range_report())


# ── JARVIS training ────────────────────────────────────────────────────────────

@app.route("/friday/training/sync", methods=["POST"])
def training_sync():
    if not TRAINING_OK:
        return jsonify({"error": "training unavailable"}), 503
    return jsonify(friday_trainer.sync_from_jarvis())


@app.route("/friday/training/status")
def training_status():
    if not TRAINING_OK:
        return jsonify({"error": "training unavailable"}), 503
    return jsonify(friday_trainer.status())


# ── Mood history + personal memory ────────────────────────────────────────────

@app.route("/friday/mood")
def mood_history():
    if not CORE_STATUS == "online":
        return jsonify({"error": "memory unavailable"}), 503
    days = request.args.get("days", 7, type=int)
    return jsonify(get_mood_history(days))


@app.route("/friday/remember", methods=["POST"])
def remember():
    data = request.get_json(silent=True) or {}
    key, value = data.get("key", "").strip(), data.get("value", "").strip()
    if not key or not value:
        return jsonify({"error": "key and value required"}), 400
    friday_remember(key, value)
    return jsonify({"status": "remembered", "key": key})


@app.route("/friday/recall")
def recall():
    key = request.args.get("key", "").strip()
    if not key:
        return jsonify({"error": "key required"}), 400
    value = friday_recall(key)
    return jsonify({"key": key, "value": value})


# ── Veronica (self-repair monitor) ────────────────────────────────────────────

@app.route("/friday/veronica/status")
def veronica_status():
    if not VERONICA_OK:
        return jsonify({"error": "veronica unavailable"}), 503
    return jsonify(veronica.get_status())


@app.route("/friday/veronica/selftest")
def veronica_selftest():
    if not VERONICA_OK:
        return jsonify({"error": "veronica unavailable"}), 503
    return jsonify(veronica.self_test())


@app.route("/friday/veronica/monitor", methods=["POST"])
def veronica_monitor():
    if not VERONICA_OK:
        return jsonify({"error": "veronica unavailable"}), 503
    return jsonify(veronica.monitor())


@app.route("/friday/veronica/baselines", methods=["POST"])
def veronica_baselines():
    if not VERONICA_OK:
        return jsonify({"error": "veronica unavailable"}), 503
    return jsonify(veronica.save_baselines())


@app.route("/friday/veronica/repair/<component>", methods=["POST"])
def veronica_repair(component):
    """Restore a component from its saved backup. Returns
    repaired=False with no backup available — never improvises a
    replacement."""
    if not VERONICA_OK:
        return jsonify({"error": "veronica unavailable"}), 503
    return jsonify(veronica.deploy_replacement(component, "manual"))


@app.route("/friday/veronica/contain/<component>", methods=["POST"])
def veronica_contain(component):
    """Manual-only: swap a component for a harmless no-op stub, backing
    up the original first."""
    if not VERONICA_OK:
        return jsonify({"error": "veronica unavailable"}), 503
    return jsonify(veronica.contain_failing_component(component))


# ── MCU capabilities ───────────────────────────────────────────────────────────

@app.route("/friday/capabilities")
def list_capabilities():
    if not CAPABILITIES_OK:
        return jsonify({"error": "capabilities unavailable"}), 503
    return jsonify({"triggers": list(CAPABILITY_MAP.keys())})


# ── Training wheels ─────────────────────────────────────────────────────────────

@app.route("/friday/trust")
def trust_status():
    if not TRAINING_WHEELS_OK:
        return jsonify({"error": "training wheels unavailable"}), 503
    return jsonify(training_wheels.status())


@app.route("/friday/trust/set", methods=["POST"])
def set_trust():
    if not TRAINING_WHEELS_OK:
        return jsonify({"error": "training wheels unavailable"}), 503
    data = request.get_json() or {}
    score = max(0, min(100, int(data.get("score", 50))))
    training_wheels._data["trust"] = score
    training_wheels._save()
    return jsonify({"trust": score})


# ── Suit Lockdown ────────────────────────────────────────────────────────────
# Bookmark this URL on a device other than your primary phone/Mac — if that
# device is lost or stolen, hitting this from anywhere locks the system down
# immediately. No auth on this route by design: the whole point is it has
# to work from a device you've never used with this account before.

@app.route("/friday/lockdown", methods=["POST"])
def trigger_lockdown():
    if not LOCKDOWN_OK:
        return jsonify({"error": "lockdown unavailable"}), 503
    return jsonify(suit_lockdown.activate(reason="remote_trigger"))


# ── Health (Apple Watch) ───────────────────────────────────────────────────────

@app.route("/friday/health/log", methods=["POST"])
def health_log():
    if not HEALTH_OK:
        return jsonify({"error": "health monitor unavailable"}), 503
    data = request.get_json(silent=True) or {}
    entry = friday_health.log_from_watch(
        heart_rate=data.get("heart_rate", 0), hrv=data.get("hrv", 0),
        blood_oxygen=data.get("blood_oxygen", 0), steps=data.get("steps", 0),
        sleep_hours=data.get("sleep_hours", 0), sleep_quality=data.get("sleep_quality", 0),
    )
    return jsonify(entry)


# ── Contacts ───────────────────────────────────────────────────────────────────

@app.route("/friday/contacts", methods=["GET"])
def contacts_list():
    if not CONTACTS_OK:
        return jsonify({"error": "contacts unavailable"}), 503
    return jsonify(friday_contacts.get_all())


@app.route("/friday/contacts/add", methods=["POST"])
def contacts_add():
    if not CONTACTS_OK:
        return jsonify({"error": "contacts unavailable"}), 503
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    return jsonify(friday_contacts.add_contact(name, data.get("relationship", "neutral"), data.get("notes", "")))


@app.route("/friday/contacts/<name>")
def contacts_intel(name):
    if not CONTACTS_OK:
        return jsonify({"error": "contacts unavailable"}), 503
    return jsonify(friday_contacts.get_intel(name))


# ── Team coordination ──────────────────────────────────────────────────────────

@app.route("/friday/team", methods=["GET"])
def team_list():
    if not TEAM_OK:
        return jsonify({"error": "team coordinator unavailable"}), 503
    return jsonify(team.get_all())


@app.route("/friday/team/update", methods=["POST"])
def team_update():
    if not TEAM_OK:
        return jsonify({"error": "team coordinator unavailable"}), 503
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    return jsonify(team.update_member(name, data.get("status", ""), data.get("task", ""), data.get("location", "")))


@app.route("/friday/team/brief")
def team_brief_route():
    if not TEAM_OK:
        return jsonify({"error": "team coordinator unavailable"}), 503
    return jsonify({"brief": team.team_brief()})


# ── Security ───────────────────────────────────────────────────────────────────

@app.route("/friday/security/status")
def security_status():
    if not SECURITY_OK:
        return jsonify({"error": "security unavailable"}), 503
    return jsonify(friday_security.get_threat_summary())


# ── Weather ────────────────────────────────────────────────────────────────────

@app.route("/friday/weather")
def weather_route():
    return jsonify({"weather": get_weather_brief()})


# ── Second Brain / News / Relationships / Code / Translate / Voice Memory ───────

@app.route("/friday/brain/ingest", methods=["POST"])
def brain_ingest():
    data = request.get_json(silent=True) or {}
    if not second_brain:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(second_brain.ingest(data.get("content", ""), data.get("source", "")))


@app.route("/friday/brain/recall")
def brain_recall():
    if not second_brain:
        return jsonify({"results": []})
    return jsonify({"results": second_brain.recall(request.args.get("q", ""))})


@app.route("/friday/brain/digest")
def brain_digest():
    if not second_brain:
        return jsonify({"digest": ""})
    return jsonify({"digest": second_brain.daily_digest()})


@app.route("/friday/news/morning")
def news_morning():
    if not news_anchor:
        return jsonify({"brief": ""})
    return jsonify({"brief": news_anchor.morning_brief()})


@app.route("/friday/news/breaking")
def news_breaking():
    if not news_anchor:
        return jsonify({"news": ""})
    return jsonify({"news": news_anchor.breaking_news(request.args.get("topic", "AI"))})


@app.route("/friday/people/log", methods=["POST"])
def people_log():
    data = request.get_json(silent=True) or {}
    if not relationships:
        return jsonify({"error": "unavailable"}), 503
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    return jsonify(relationships.log_contact(name, data.get("notes", "")))


@app.route("/friday/people/attention")
def people_attention():
    if not relationships:
        return jsonify({"people": []})
    return jsonify({"people": relationships.who_needs_attention()})


@app.route("/friday/translate", methods=["POST"])
def translate_endpoint():
    data = request.get_json(silent=True) or {}
    if not translator:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(translator.translate(data.get("text", ""), data.get("target", "English")))


@app.route("/friday/code/review", methods=["POST"])
def code_review():
    data = request.get_json(silent=True) or {}
    if not friday_code:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(friday_code.quick_review(data.get("code", ""), data.get("language", "")))


@app.route("/friday/code/fix", methods=["POST"])
def code_fix():
    data = request.get_json(silent=True) or {}
    if not friday_code:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(friday_code.fix(data.get("code", ""), data.get("error", "")))


@app.route("/friday/voice/weekly")
def voice_weekly():
    if not voice_memory:
        return jsonify({"report": ""})
    return jsonify({"report": voice_memory.weekly_report()})


# ── Notes / Tasks ────────────────────────────────────────────────────────────

@app.route("/friday/notes")
def friday_notes():
    from core.friday_memory import get_notes
    return jsonify({"notes": get_notes()})


@app.route("/friday/tasks")
def friday_tasks():
    return jsonify({"tasks": get_tasks()})


@app.route("/friday/tasks/add", methods=["POST"])
def friday_tasks_add():
    data = request.get_json(silent=True) or {}
    task = data.get("task", "").strip()
    if not task:
        return jsonify({"error": "task required"}), 400
    return jsonify(add_task(task, data.get("priority", "normal")))


@app.route("/friday/tasks/complete", methods=["POST"])
def friday_tasks_complete():
    data = request.get_json(silent=True) or {}
    task_id = data.get("id")
    if task_id is None:
        return jsonify({"error": "id required"}), 400
    complete_task(int(task_id))
    return jsonify({"completed": True, "id": task_id})


# ── Workouts / Bills ─────────────────────────────────────────────────────────

@app.route("/friday/workout/log", methods=["POST"])
def workout_log():
    data = request.get_json(silent=True) or {}
    log_workout(data.get("type", "workout"), data.get("duration", 0))
    return jsonify({"logged": True})


@app.route("/friday/workout/streak")
def workout_streak():
    if not WORKOUT_FILE.exists():
        return jsonify({"streak": 0})
    try:
        workouts = json.loads(WORKOUT_FILE.read_text())
    except Exception:
        return jsonify({"streak": 0})

    dates = sorted(set(w["ts"][:10] for w in workouts), reverse=True)
    streak = 0
    expected = datetime.datetime.now().date()
    for date_str in dates:
        date = datetime.datetime.fromisoformat(date_str).date()
        if date >= expected - datetime.timedelta(days=1):
            streak += 1
            expected = date - datetime.timedelta(days=1)
        else:
            break
    return jsonify({"streak": streak, "dates": dates[:7]})


@app.route("/friday/bills/add", methods=["POST"])
def add_bill():
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    bills = []
    if BILLS_FILE.exists():
        try:
            bills = json.loads(BILLS_FILE.read_text())
        except Exception:
            bills = []
    bills.append({
        "name": name, "amount": data.get("amount", 0),
        "due_day": data.get("due_day", 1),
        "added": datetime.datetime.now().isoformat(),
    })
    BILLS_FILE.parent.mkdir(parents=True, exist_ok=True)
    BILLS_FILE.write_text(json.dumps(bills, indent=2))
    return jsonify({"added": True})


# ── Calls ────────────────────────────────────────────────────────────────────

@app.route("/friday/call/log", methods=["POST"])
def log_call():
    """Called after a call ends via iOS Shortcut."""
    data = request.get_json(silent=True) or {}
    contact = data.get("contact", "")
    duration = data.get("duration", 0)
    notes = data.get("notes", "")

    if contact and relationships:
        relationships.log_contact(contact, notes=f"Call ({duration} min): {notes}")

    response = f"Call with {contact} logged, boss." if contact else "Call logged, boss."
    if friday_brain:
        result = friday_brain.think(
            f"Call ended with {contact}. Duration: {duration} minutes. Notes: {notes}\n\n"
            f"Brief acknowledgment. Under 10 words."
        )
        response = result["response"] or response

    return jsonify({"response": response, "logged": True})


# ── Email ────────────────────────────────────────────────────────────────────

@app.route("/friday/email/summary")
def email_summary():
    if not friday_gmail:
        return jsonify({"summary": "Gmail not configured"})
    return jsonify({"summary": friday_gmail.summarize_inbox()})


@app.route("/friday/email/urgent")
def email_urgent():
    if not friday_gmail:
        return jsonify({"urgent": []})
    return jsonify({"urgent": friday_gmail.get_urgent()})


@app.route("/friday/email/draft", methods=["POST"])
def email_draft():
    data = request.get_json(silent=True) or {}
    if not friday_gmail:
        return jsonify({"error": "Gmail not configured"}), 503
    return jsonify(friday_gmail.draft_reply(
        email_subject=data.get("subject", ""), email_from=data.get("from", ""),
        email_body=data.get("body", ""), instruction=data.get("instruction", ""),
    ))


@app.route("/friday/email/triage")
def email_triage():
    if not friday_gmail:
        return jsonify({"error": "Gmail not configured"}), 503
    return jsonify(friday_gmail.smart_triage())


# ── Goals ────────────────────────────────────────────────────────────────────

@app.route("/friday/goals")
def get_goals():
    if not goals:
        return jsonify([])
    return jsonify(goals.get_active_goals())


@app.route("/friday/goals/add", methods=["POST"])
def add_goal():
    data = request.get_json(silent=True) or {}
    if not goals:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(goals.add_goal(
        data.get("name", ""), data.get("description", ""),
        data.get("target_date", ""), data.get("milestones", []),
    ))


@app.route("/friday/goals/progress", methods=["POST"])
def log_goal_progress():
    data = request.get_json(silent=True) or {}
    if not goals:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(goals.log_progress(
        data.get("goal_id", ""), data.get("work", ""), auto_detect=True,
    ))


@app.route("/friday/goals/report")
def goal_report():
    if not goals:
        return jsonify({"report": ""})
    return jsonify({"report": goals.weekly_progress_report()})


# ── Spotify ──────────────────────────────────────────────────────────────────

@app.route("/friday/spotify/auth")
def spotify_auth():
    if not friday_spotify:
        return "Spotify not configured", 500
    return redirect(friday_spotify.auth_url())


@app.route("/friday/spotify/callback")
def spotify_callback():
    if not friday_spotify:
        return "Spotify not configured", 500
    code = request.args.get("code", "")
    if not code:
        return jsonify({"error": request.args.get("error", "No code provided")}), 400
    result = friday_spotify.exchange_code(code)
    if result.get("ok"):
        return "Spotify connected. You can close this tab, boss."
    return jsonify(result), 400


# ── Calendar ─────────────────────────────────────────────────────────────────

@app.route("/friday/calendar/auth")
def calendar_auth():
    if not friday_calendar or not friday_calendar.is_configured():
        return "Calendar not configured", 500
    return redirect(friday_calendar.auth_url())


@app.route("/friday/calendar/callback")
def calendar_callback():
    if not friday_calendar:
        return "Calendar not configured", 500
    code = request.args.get("code", "")
    if not code:
        return jsonify({"error": request.args.get("error", "No code provided")}), 400
    result = friday_calendar.exchange_code(code)
    if result.get("ok"):
        return "Calendar connected. You can close this tab, boss."
    return jsonify(result), 400


@app.route("/friday/calendar/today")
def calendar_today():
    if not friday_calendar:
        return jsonify({"events": []})
    return jsonify({"events": friday_calendar.get_today()})


@app.route("/friday/calendar/upcoming")
def calendar_upcoming():
    if not friday_calendar:
        return jsonify({"events": []})
    hours = request.args.get("hours", 24, type=int)
    return jsonify({"events": friday_calendar.get_upcoming(hours)})


# ── Habits / Journal / Focus ─────────────────────────────────────────────────

@app.route("/friday/habits")
def get_habits():
    if not habits:
        return jsonify({})
    return jsonify(habits.all_streaks())


@app.route("/friday/habits/log", methods=["POST"])
def log_habit():
    data = request.get_json(silent=True) or {}
    name = data.get("habit", "").strip()
    if not name or not habits:
        return jsonify({"error": "No habit"}), 400
    return jsonify(habits.log(name))


@app.route("/friday/journal/log", methods=["POST"])
def journal_log():
    data = request.get_json(silent=True) or {}
    content = data.get("content", "").strip()
    if not content or not journal:
        return jsonify({"error": "No content"}), 400
    return jsonify(journal.log_entry(content))


@app.route("/friday/journal/reflection")
def journal_reflection():
    if not journal:
        return jsonify({"reflection": ""})
    return jsonify({"reflection": journal.weekly_reflection()})


@app.route("/friday/focus/status")
def focus_status():
    return jsonify(_FOCUS_SESSION)


# ── Advanced reasoning ───────────────────────────────────────────────────────
# Opt-in / on-demand only — same convention as JARVIS_V5's
# server/routes/brain_enhancement.py: none of this is wired into casual
# chat triggers, since each of these costs multiple LLM calls per
# invocation (deep_think alone is 3 real calls). Use these when you
# explicitly want FRIDAY to think harder about something specific.

@app.route("/friday/reason/deep", methods=["POST"])
def reason_deep():
    data = request.get_json(silent=True) or {}
    if not friday_brain:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(friday_brain.deep_think(data.get("query", ""), data.get("context", "")))


@app.route("/friday/reason/critique", methods=["POST"])
def reason_critique():
    data = request.get_json(silent=True) or {}
    if not friday_brain:
        return jsonify({"error": "unavailable"}), 503
    improved = friday_brain.self_critique(data.get("query", ""), data.get("response", ""))
    return jsonify({"improved": improved})


@app.route("/friday/reason/parallel", methods=["POST"])
def reason_parallel():
    data = request.get_json(silent=True) or {}
    if not friday_brain:
        return jsonify({"error": "unavailable"}), 503
    return jsonify({"response": friday_brain.parallel_think(data.get("query", ""))})


# ── Military-grade systems (OODA, EMCON, scenario/Sokovia) ──────────────────────
# On-demand/opt-in only, same as JARVIS's /stark equivalents — none of
# these are auto-triggered by regular chat.

@app.route("/friday/ooda", methods=["POST"])
def friday_ooda():
    data = request.get_json(silent=True) or {}
    from core.ooda import ooda
    return jsonify(ooda.run(data.get("situation", ""), data.get("context", "")))


@app.route("/friday/ooda/rapid", methods=["POST"])
def friday_ooda_rapid():
    data = request.get_json(silent=True) or {}
    from core.ooda import ooda
    return jsonify({"result": ooda.rapid_ooda(data.get("situation", ""))})


@app.route("/friday/emcon")
def friday_emcon_status():
    from services.emcon import emcon
    return jsonify(emcon.status())


@app.route("/friday/emcon/activate", methods=["POST"])
def friday_emcon_activate():
    data = request.get_json(silent=True) or {}
    from services.emcon import emcon
    return jsonify(emcon.activate(data.get("level", 2), data.get("reason", "")))


@app.route("/friday/emcon/deactivate", methods=["POST"])
def friday_emcon_deactivate():
    from services.emcon import emcon
    return jsonify(emcon.deactivate())


@app.route("/friday/scenarios/futures", methods=["POST"])
def friday_scenarios_futures():
    data = request.get_json(silent=True) or {}
    from core.scenario_engine import scenario_engine
    return jsonify(scenario_engine.analyze_futures(data.get("situation", ""), data.get("n_scenarios", 6)))


@app.route("/friday/sokovia/evacuation", methods=["POST"])
def friday_sokovia_evacuation():
    data = request.get_json(silent=True) or {}
    from core.sokovia import sokovia
    return jsonify(sokovia.evacuation_analysis(data.get("situation", ""), data.get("location", ""),
                                               data.get("population", 0)))


@app.route("/friday/sokovia/safe-action", methods=["POST"])
def friday_sokovia_safe_action():
    data = request.get_json(silent=True) or {}
    from core.sokovia import sokovia
    return jsonify(sokovia.calculate_safe_action(data.get("action", ""), data.get("constraints", [])))


# ── Self-maintenance ─────────────────────────────────────────────────────────

@app.route("/friday/system/config-check")
def friday_config_check():
    from core.config_validator import check
    return jsonify(check())


@app.route("/friday/system/doctor")
def friday_system_doctor():
    from services import system_doctor
    return jsonify(system_doctor.full_check())


@app.route("/friday/system/cleanup", methods=["POST"])
def friday_system_cleanup():
    from services import disk_cleanup
    return jsonify(disk_cleanup.clean())


# ── Budget ─────────────────────────────────────────────────────────────────────

@app.route("/budget")
def budget_status():
    try:
        import budget_2 as budget
        return jsonify(budget.status())
    except Exception as e:
        return jsonify({"error": str(e)})


# ── HUD ────────────────────────────────────────────────────────────────────────

@app.route("/hud")
def hud():
    return FRIDAY_HUD_HTML


FRIDAY_HUD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>F.R.I.D.A.Y</title>
<style>

/* ==================================
   FRIDAY HOLOGRAPHIC DESIGN
   Deep space blue. Floating glass.
==================================== */

:root {
  --space:    #000814;
  --deep:     #001233;
  --mid:      #023e8a;
  --accent:   #0096c7;
  --bright:   #48cae4;
  --ice:      #90e0ef;
  --glow:     #00b4d8;
  --text:     #caf0f8;
  --muted:    #1a6b8a;
  --glass:    rgba(0,150,199,0.06);
  --glass2:   rgba(0,150,199,0.12);
  --border:   rgba(72,202,228,0.2);
  --border2:  rgba(72,202,228,0.08);
  --warn:     #f77f00;
  --danger:   #e63946;
  --green:    #2dc653;
}

* { box-sizing:border-box; margin:0; padding:0; }

body {
  background: var(--space);
  background-image:
    radial-gradient(ellipse at 20% 50%, rgba(2,62,138,0.15) 0%, transparent 60%),
    radial-gradient(ellipse at 80% 20%, rgba(0,150,199,0.1) 0%, transparent 50%);
  color: var(--text);
  font-family: -apple-system, 'SF Pro Display', 'Helvetica Neue', sans-serif;
  height: 100vh;
  overflow: hidden;
  position: relative;
}

.particles { position: fixed; inset: 0; pointer-events: none; z-index: 0; overflow: hidden; }
.particle {
  position: absolute; width: 2px; height: 2px; border-radius: 50%;
  background: var(--bright); opacity: 0; animation: float-particle linear infinite;
}
@keyframes float-particle {
  0%   { opacity: 0; transform: translateY(100vh) scale(0); }
  10%  { opacity: 0.6; }
  90%  { opacity: 0.3; }
  100% { opacity: 0; transform: translateY(-10vh) scale(1); }
}

.chat-screen { position: fixed; inset: 0; display: flex; flex-direction: column; z-index: 1; }

.top-bar {
  position: relative; display: flex; align-items: center; padding: 12px 20px; gap: 16px;
  background: linear-gradient(180deg, rgba(0,8,20,0.95) 0%, rgba(0,8,20,0) 100%);
  z-index: 10;
}

.friday-logo { display: flex; align-items: center; gap: 10px; }
.logo-orb {
  width: 32px; height: 32px; border-radius: 50%;
  background: radial-gradient(circle, var(--bright) 0%, var(--accent) 40%, transparent 70%);
  box-shadow: 0 0 20px rgba(72,202,228,0.5), 0 0 40px rgba(0,150,199,0.2);
  animation: orb-breathe 4s ease-in-out infinite; flex-shrink: 0;
}
@keyframes orb-breathe {
  0%,100% { transform: scale(1); box-shadow: 0 0 20px rgba(72,202,228,0.5), 0 0 40px rgba(0,150,199,0.2); }
  50%     { transform: scale(1.15); box-shadow: 0 0 30px rgba(72,202,228,0.7), 0 0 60px rgba(0,150,199,0.4); }
}
.logo-text-wrap { display: flex; flex-direction: column; }
.logo-name { font-size: 16px; font-weight: 700; letter-spacing: 6px; color: var(--bright); text-shadow: 0 0 20px rgba(72,202,228,0.5); }
.logo-version { font-size: 9px; letter-spacing: 2px; color: var(--muted); margin-top: 1px; }

.top-pills { display: flex; gap: 8px; align-items: center; }
.pill {
  padding: 4px 12px; border-radius: 20px; font-size: 10px; letter-spacing: 1px;
  backdrop-filter: blur(10px); border: 1px solid var(--border2); background: var(--glass);
  color: var(--text); white-space: nowrap;
}
.pill.online { border-color: rgba(45,198,83,0.4); background: rgba(45,198,83,0.08); color: var(--green); }
.pill.warn   { border-color: rgba(247,127,0,0.4); background: rgba(247,127,0,0.08); color: var(--warn); }

.top-right { margin-left: auto; display: flex; align-items: center; gap: 10px; }
.clock-display { font-size: 18px; font-weight: 300; letter-spacing: 3px; color: var(--text); font-variant-numeric: tabular-nums; }
.panel-toggle {
  width: 34px; height: 34px; border-radius: 50%; border: 1px solid var(--border);
  background: var(--glass); backdrop-filter: blur(10px); cursor: pointer;
  display: flex; align-items: center; justify-content: center; font-size: 14px;
  color: var(--bright); transition: all 0.2s;
}
.panel-toggle:hover { background: var(--glass2); box-shadow: 0 0 12px rgba(72,202,228,0.2); }
.voice-mode-btn {
  width: auto; border-radius: 16px; padding: 0 12px; font-size: 10px; font-weight: 600;
  letter-spacing: 0.6px; white-space: nowrap;
}
.voice-mode-btn.on {
  border-color: rgba(72,202,228,0.5); color: var(--bright); background: var(--glass2);
  box-shadow: 0 0 12px rgba(72,202,228,0.25); animation: mic-pulse 1.6s ease-in-out infinite;
}

.messages-area {
  flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column;
  gap: 12px; min-height: 0; scroll-behavior: smooth;
}
.messages-area::-webkit-scrollbar { width: 3px; }
.messages-area::-webkit-scrollbar-track { background: transparent; }
.messages-area::-webkit-scrollbar-thumb { background: var(--muted); border-radius: 2px; }

.msg-wrap { display: flex; flex-direction: column; animation: msg-appear 0.3s ease; max-width: 80%; }
@keyframes msg-appear { from { opacity:0; transform: translateY(8px); } to { opacity:1; transform: translateY(0); } }
.msg-wrap.user { align-self: flex-end; align-items: flex-end; }
.msg-wrap.fri  { align-self: flex-start; align-items: flex-start; }
.msg-wrap.sys  { align-self: center; align-items: center; max-width: 60%; }

.msg-who { font-size: 10px; letter-spacing: 2px; margin-bottom: 4px; font-weight: 600; }
.msg-wrap.user .msg-who { color: rgba(144,224,239,0.6); }
.msg-wrap.fri  .msg-who { color: rgba(72,202,228,0.6); }
.msg-wrap.sys  .msg-who { color: var(--muted); }

.msg-bubble { padding: 12px 18px; border-radius: 20px; font-size: 14px; line-height: 1.6; position: relative; max-width: 100%; }
.msg-wrap.user .msg-bubble {
  background: linear-gradient(135deg, rgba(0,150,199,0.2) 0%, rgba(0,180,216,0.15) 100%);
  border: 1px solid rgba(72,202,228,0.25); border-bottom-right-radius: 4px;
  backdrop-filter: blur(10px); color: var(--ice);
}
.msg-wrap.fri .msg-bubble {
  background: linear-gradient(135deg, rgba(2,62,138,0.3) 0%, rgba(0,70,150,0.2) 100%);
  border: 1px solid rgba(72,202,228,0.15); border-bottom-left-radius: 4px;
  backdrop-filter: blur(10px); color: var(--text);
  box-shadow: 0 4px 20px rgba(0,0,0,0.3), 0 0 0 1px rgba(72,202,228,0.05);
}
.msg-wrap.sys .msg-bubble {
  background: rgba(0,150,199,0.05); border: 1px solid var(--border2); border-radius: 10px;
  font-size: 11px; color: var(--muted); font-style: italic; backdrop-filter: blur(4px);
}

.msg-meta { display: flex; gap: 8px; margin-top: 4px; align-items: center; }
.msg-model-badge {
  font-size: 9px; padding: 2px 8px; border-radius: 10px; border: 1px solid var(--border2);
  background: var(--glass); color: var(--muted); letter-spacing: 1px;
}
.msg-ms { font-size: 9px; color: var(--muted); }
.msg-emotion {
  font-size: 9px; padding: 2px 8px; border-radius: 10px;
  border: 1px solid rgba(72,202,228,0.15); background: rgba(72,202,228,0.06); color: var(--bright);
}

.thinking-bubble {
  align-self: flex-start; display: flex; align-items: center; gap: 10px;
  padding: 12px 18px; border-radius: 20px; border-bottom-left-radius: 4px;
  background: linear-gradient(135deg, rgba(2,62,138,0.3) 0%, rgba(0,70,150,0.2) 100%);
  border: 1px solid rgba(72,202,228,0.15); backdrop-filter: blur(10px); animation: msg-appear 0.2s ease;
}
.think-dots-wrap { display: flex; gap: 5px; }
.tdot { width: 6px; height: 6px; border-radius: 50%; background: var(--bright); animation: tdot-bounce 1.2s ease-in-out infinite; }
.tdot:nth-child(2) { animation-delay: 0.2s; }
.tdot:nth-child(3) { animation-delay: 0.4s; }
@keyframes tdot-bounce { 0%,80%,100% { transform:scale(0.6); opacity:0.3; } 40% { transform:scale(1); opacity:1; } }
.thinking-text { font-size: 12px; color: var(--muted); letter-spacing: 2px; }

.input-zone { padding: 16px 20px 20px; background: linear-gradient(0deg, rgba(0,8,20,0.98) 0%, rgba(0,8,20,0) 100%); position: relative; }
.quick-actions { display: flex; gap: 8px; margin-bottom: 12px; overflow-x: auto; scrollbar-width: none; padding-bottom: 2px; }
.quick-actions::-webkit-scrollbar { display:none; }
.qa-btn {
  padding: 5px 14px; border-radius: 16px; border: 1px solid var(--border2); background: var(--glass);
  color: var(--muted); font-size: 11px; cursor: pointer; white-space: nowrap;
  backdrop-filter: blur(10px); transition: all 0.2s; flex-shrink: 0;
}
.qa-btn:hover { border-color: var(--border); color: var(--bright); background: var(--glass2); }

.input-row {
  display: flex; align-items: center; gap: 10px; background: var(--glass2);
  border: 1px solid var(--border); border-radius: 28px; padding: 8px 8px 8px 20px;
  backdrop-filter: blur(20px);
  box-shadow: 0 4px 30px rgba(0,0,0,0.4), 0 0 0 1px rgba(72,202,228,0.05), inset 0 1px 0 rgba(72,202,228,0.05);
  transition: border-color 0.2s, box-shadow 0.2s;
}
.input-row:focus-within {
  border-color: rgba(72,202,228,0.4);
  box-shadow: 0 4px 30px rgba(0,0,0,0.4), 0 0 20px rgba(72,202,228,0.1), inset 0 1px 0 rgba(72,202,228,0.1);
}
.chat-inp { flex: 1; background: transparent; border: none; outline: none; color: var(--text); font-size: 15px; font-family: inherit; letter-spacing: 0.3px; }
.chat-inp::placeholder { color: var(--muted); }
.voice-hint { font-size: 11px; color: var(--muted); letter-spacing: 0.3px; margin-top: 6px; padding-left: 4px; }

.mic-btn {
  width: 36px; height: 36px; border-radius: 50%; border: 1px solid var(--border2); background: var(--glass);
  color: var(--muted); cursor: pointer; display: flex; align-items:center; justify-content:center;
  font-size: 16px; transition: all 0.2s; flex-shrink: 0;
}
.mic-btn:hover, .mic-btn.on { border-color: rgba(72,202,228,0.4); color: var(--bright); background: var(--glass2); box-shadow: 0 0 12px rgba(72,202,228,0.2); }
.mic-btn.on { animation: mic-pulse 0.8s ease-in-out infinite; }
@keyframes mic-pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(72,202,228,0.3); } 50% { box-shadow: 0 0 0 6px rgba(72,202,228,0); } }

.send-btn {
  width: 40px; height: 40px; border-radius: 50%; border: none;
  background: linear-gradient(135deg, var(--accent) 0%, var(--bright) 100%);
  color: var(--space); cursor: pointer; display: flex; align-items:center; justify-content:center;
  font-size: 16px; transition: all 0.2s; flex-shrink: 0; box-shadow: 0 4px 15px rgba(0,150,199,0.4);
}
.send-btn:hover { transform: scale(1.05); box-shadow: 0 6px 20px rgba(0,150,199,0.6); }

.slide-panel {
  position: fixed; top: 0; bottom: 0; width: 320px;
  background: linear-gradient(135deg, rgba(0,18,51,0.85) 0%, rgba(0,8,20,0.9) 100%);
  backdrop-filter: blur(30px); border: 1px solid var(--border); z-index: 100;
  transition: transform 0.35s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex; flex-direction: column; overflow: hidden;
}
.slide-panel::before {
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px;
  background: linear-gradient(90deg, transparent, var(--bright), transparent); opacity: 0.5;
}
.slide-panel::after {
  content: ''; position: absolute; inset: 0;
  background: linear-gradient(135deg, rgba(72,202,228,0.03) 0%, transparent 60%); pointer-events: none;
}
.panel-left { left: 0; border-right: 1px solid var(--border); border-left: none; transform: translateX(-100%); box-shadow: 4px 0 40px rgba(0,0,0,0.5); }
.panel-left.open { transform: translateX(0); }
.panel-right { right: 0; border-left: 1px solid var(--border); border-right: none; transform: translateX(100%); box-shadow: -4px 0 40px rgba(0,0,0,0.5); }
.panel-right.open { transform: translateX(0); }

.panel-header { padding: 16px 18px; border-bottom: 1px solid var(--border2); display: flex; align-items: center; justify-content: space-between; flex-shrink: 0; }
.panel-title { font-size: 11px; letter-spacing: 4px; color: var(--bright); font-weight: 600; }
.panel-close {
  width: 28px; height: 28px; border-radius: 50%; border: 1px solid var(--border2); background: transparent;
  color: var(--muted); cursor: pointer; display: flex; align-items:center; justify-content:center; font-size: 14px; transition: all 0.2s;
}
.panel-close:hover { border-color: var(--border); color: var(--bright); }

.panel-content { flex: 1; overflow-y: auto; padding: 16px; scrollbar-width: thin; scrollbar-color: var(--muted) transparent; }
.p-section { margin-bottom: 20px; }
.p-section-title { font-size: 9px; letter-spacing: 3px; color: var(--muted); margin-bottom: 10px; text-transform: uppercase; }

.stat-card { background: var(--glass); border: 1px solid var(--border2); border-radius: 12px; padding: 12px 14px; margin-bottom: 8px; transition: border-color 0.2s; }
.stat-card:hover { border-color: var(--border); }
.stat-card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.stat-card-label { font-size: 10px; letter-spacing: 1px; color: var(--muted); }
.stat-card-value { font-size: 16px; font-weight: 700; color: var(--text); letter-spacing: 1px; }
.stat-card-value.green  { color: var(--green); }
.stat-card-value.warn   { color: var(--warn); }
.stat-card-value.danger { color: var(--danger); }
.stat-card-value.bright { color: var(--bright); }

.stat-bar { height: 3px; background: rgba(72,202,228,0.1); border-radius: 2px; overflow: hidden; }
.stat-bar-fill { height: 100%; border-radius: 2px; background: linear-gradient(90deg, var(--accent), var(--bright)); box-shadow: 0 0 6px rgba(72,202,228,0.4); transition: width 1s ease; }
.stat-bar-fill.warn { background: linear-gradient(90deg, #cc4400, var(--warn)); box-shadow: 0 0 6px rgba(247,127,0,0.4); }

.info-row { display: flex; justify-content: space-between; align-items: center; padding: 7px 0; border-bottom: 1px solid var(--border2); font-size: 11px; }
.info-row:last-child { border-bottom: none; }
.info-label { color: var(--muted); }
.info-val   { color: var(--text); }
.info-val.green  { color: var(--green); }
.info-val.bright { color: var(--bright); }
.info-val.warn   { color: var(--warn); }
.info-val.danger { color: var(--danger); }

.veronica-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.ver-card { background: var(--glass); border: 1px solid var(--border2); border-radius: 10px; padding: 10px 12px; text-align: center; }
.ver-card-val { font-size: 20px; font-weight: 700; color: var(--bright); }
.ver-card-label { font-size: 9px; letter-spacing: 2px; color: var(--muted); margin-top: 2px; }

.emotion-grid { display: flex; flex-wrap: wrap; gap: 6px; }
.emotion-badge { padding: 4px 10px; border-radius: 10px; background: var(--glass); border: 1px solid var(--border2); font-size: 10px; color: var(--bright); }

.protocol-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.proto-btn {
  padding: 8px 10px; border-radius: 8px; border: 1px solid var(--border2); background: var(--glass);
  color: var(--muted); font-size: 9px; letter-spacing: 1px; cursor: pointer; text-align: center;
  transition: all 0.2s; font-family: inherit;
}
.proto-btn:hover { border-color: var(--border); color: var(--bright); background: var(--glass2); }

.mode-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px; }
.mode-btn {
  padding: 8px 4px; border-radius: 8px; border: 1px solid var(--border2); background: var(--glass);
  color: var(--muted); font-size: 9px; letter-spacing: 1px; cursor: pointer; text-align: center;
  transition: all 0.2s; font-family: inherit;
}
.mode-btn:hover, .mode-btn.active { border-color: rgba(72,202,228,0.4); color: var(--bright); background: rgba(72,202,228,0.08); }

.backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.4); backdrop-filter: blur(2px); z-index: 99; opacity: 0; pointer-events: none; transition: opacity 0.3s; }
.backdrop.on { opacity: 1; pointer-events: all; }

.status-orb {
  position: fixed; bottom: 100px; right: 20px; width: 48px; height: 48px; border-radius: 50%;
  background: var(--glass2); border: 1px solid var(--border); backdrop-filter: blur(20px);
  display: flex; align-items:center; justify-content:center; cursor: pointer; z-index: 20;
  transition: all 0.2s; box-shadow: 0 4px 20px rgba(0,0,0,0.4);
}
.status-orb:hover { box-shadow: 0 0 20px rgba(72,202,228,0.2); border-color: var(--border); }
.status-orb-dot { width: 12px; height: 12px; border-radius: 50%; background: var(--green); box-shadow: 0 0 8px var(--green); animation: orb-breathe 2s ease-in-out infinite; }

.cov-banner {
  position: fixed; top: 70px; left: 50%; transform: translateX(-50%); padding: 8px 20px; border-radius: 20px;
  background: rgba(247,127,0,0.1); border: 1px solid rgba(247,127,0,0.3); backdrop-filter: blur(10px);
  font-size: 11px; letter-spacing: 2px; color: var(--warn); z-index: 50; display: none;
}
.cov-banner.on { display: block; }

.mute-float {
  position: fixed; bottom: 160px; right: 20px; width: 40px; height: 40px; border-radius: 50%;
  background: var(--glass); border: 1px solid var(--border2); backdrop-filter: blur(20px);
  display: flex; align-items:center; justify-content:center; cursor: pointer; z-index: 20;
  font-size: 16px; color: var(--muted); transition: all 0.2s;
}
.mute-float.on { border-color: rgba(247,127,0,0.4); color: var(--warn); }

/* Holographic face — sits behind the message bubbles (transparent
   background, see .messages-area above) but above the particle field,
   so it reads as a projection glimpsed through the chat rather than a
   separate screen. Own z-index tier (0, tied with .particles) — later
   in the DOM so it paints over particles, but .chat-screen's z-index:1
   still wins over it for every real UI element. */
#friday-face {
  position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
  z-index: 0; opacity: 0; pointer-events: none;
  transition: opacity 0.6s ease;
  filter: drop-shadow(0 0 20px rgba(72,202,228,0.35));
}
#friday-face.on { opacity: 0.85; }

</style>
</head>
<body>

<div class="particles" id="particles"></div>
<canvas id="friday-face" width="220" height="220"></canvas>
<div class="cov-banner" id="cov-banner">COVERAGE MODE - JARVIS OFFLINE</div>
<div class="backdrop" id="backdrop" onclick="closeAll()"></div>

<!-- LEFT PANEL - Systems -->
<div class="slide-panel panel-left" id="panel-left">
  <div class="panel-header">
    <div class="panel-title">SYSTEMS</div>
    <button class="panel-close" onclick="toggleLeft()">&times;</button>
  </div>
  <div class="panel-content">

    <div class="p-section">
      <div class="p-section-title">DIAGNOSTICS</div>
      <div class="stat-card">
        <div class="stat-card-header"><span class="stat-card-label">CPU</span><span class="stat-card-value bright" id="p-cpu">-%</span></div>
        <div class="stat-bar"><div class="stat-bar-fill" id="p-cpu-bar" style="width:0%"></div></div>
      </div>
      <div class="stat-card">
        <div class="stat-card-header"><span class="stat-card-label">MEMORY</span><span class="stat-card-value" id="p-ram">-%</span></div>
        <div class="stat-bar"><div class="stat-bar-fill" id="p-ram-bar" style="width:0%"></div></div>
      </div>
    </div>

    <div class="p-section">
      <div class="p-section-title">STATUS</div>
      <div class="info-row"><span class="info-label">UPTIME</span><span class="info-val bright" id="p-uptime">-</span></div>
      <div class="info-row"><span class="info-label">JARVIS</span><span class="info-val" id="p-jarvis">-</span></div>
      <div class="info-row"><span class="info-label">COVERAGE</span><span class="info-val" id="p-coverage">STANDBY</span></div>
      <div class="info-row"><span class="info-label">MODE</span><span class="info-val bright" id="p-mode">NORMAL</span></div>
      <div class="info-row"><span class="info-label">API CALLS</span><span class="info-val" id="p-calls">-</span></div>
    </div>

    <div class="p-section">
      <div class="p-section-title">SECURITY</div>
      <div class="info-row"><span class="info-label">THREATS</span><span class="info-val danger" id="p-threats">0</span></div>
      <div class="info-row"><span class="info-label">BLOCKED IPS</span><span class="info-val warn" id="p-blocked">0</span></div>
    </div>

    <div class="p-section">
      <div class="p-section-title">VERONICA</div>
      <div class="veronica-grid">
        <div class="ver-card"><div class="ver-card-val" id="v-backed">-</div><div class="ver-card-label">BACKED UP</div></div>
        <div class="ver-card"><div class="ver-card-val" id="v-repairs">0</div><div class="ver-card-label">REPAIRS</div></div>
      </div>
    </div>

    <div class="p-section">
      <div class="p-section-title">VOICE MODE</div>
      <div class="mode-grid">
        <button class="mode-btn active" onclick="setMode('normal')">NORMAL</button>
        <button class="mode-btn" onclick="setMode('focused')">FOCUSED</button>
        <button class="mode-btn" onclick="setMode('support')">SUPPORT</button>
        <button class="mode-btn" onclick="setMode('coverage')">COVERAGE</button>
      </div>
    </div>

    <div class="p-section">
      <div class="p-section-title">TRAINING WHEELS</div>
      <div class="stat-card">
        <div class="stat-card-header"><span class="stat-card-label">TRUST TIER</span><span class="stat-card-value bright" id="trust-tier">-</span></div>
        <div class="stat-bar"><div class="stat-bar-fill" id="trust-bar" style="width:0%"></div></div>
      </div>
    </div>

  </div>
</div>

<!-- RIGHT PANEL - Intelligence -->
<div class="slide-panel panel-right" id="panel-right">
  <div class="panel-header">
    <div class="panel-title">INTELLIGENCE</div>
    <button class="panel-close" onclick="toggleRight()">&times;</button>
  </div>
  <div class="panel-content">

    <div class="p-section">
      <div class="p-section-title">EMOTIONAL TREND</div>
      <div class="emotion-grid" id="p-emotions"><div class="emotion-badge">NEUTRAL</div></div>
    </div>

    <div class="p-section">
      <div class="p-section-title">TRAINING</div>
      <div class="info-row"><span class="info-label">FACTS LEARNED</span><span class="info-val bright" id="p-training">-</span></div>
    </div>

    <div class="p-section">
      <div class="p-section-title">PROTOCOLS</div>
      <div class="protocol-grid">
        <button class="proto-btn" onclick="runProto(1)">P1 COVERAGE</button>
        <button class="proto-btn" onclick="runProto(3)">P3 DARK MODE</button>
        <button class="proto-btn" onclick="runProto(16)">P16 CHECK-IN</button>
        <button class="proto-btn" onclick="runProto(20)">P20 MORNING</button>
      </div>
    </div>

    <div class="p-section">
      <div class="p-section-title">QUICK LINKS</div>
      <div class="info-row"><a href="/friday/veronica/selftest" target="_blank" style="color:var(--bright);text-decoration:none;font-size:11px">Veronica Self-Test -&gt;</a></div>
      <div class="info-row"><a href="/friday/protocols" target="_blank" style="color:var(--bright);text-decoration:none;font-size:11px">All Protocols -&gt;</a></div>
    </div>

  </div>
</div>

<!-- MAIN CHAT SCREEN -->
<div class="chat-screen">

  <div class="top-bar">
    <div class="friday-logo">
      <canvas id="friday-arc" width="32" height="32" style="border-radius:50%;display:block"></canvas>
      <div class="logo-text-wrap">
        <div class="logo-name">F.R.I.D.A.Y</div>
        <div class="logo-version">HOLOGRAPHIC INTERFACE</div>
      </div>
    </div>

    <div class="top-pills">
      <div class="pill online" id="status-pill">ONLINE</div>
      <div class="pill" id="jarvis-pill">JARVIS -</div>
      <div class="pill" id="model-pill">NORMAL</div>
    </div>

    <div class="top-right">
      <div class="clock-display" id="clock">--:--:--</div>
      <button class="panel-toggle voice-mode-btn" id="voice-mode-btn" onclick="toggleVoiceMode()" title="Hands-free wake-word listening">VOICE OFF</button>
      <button class="panel-toggle voice-mode-btn" id="enroll-voice-btn" onclick="enrollVoice()" title="Enroll your voice for speaker verification">&#127908; ENROLL MY VOICE</button>
      <button class="panel-toggle" onclick="toggleLeft()" title="Systems">&#9881;</button>
      <button class="panel-toggle" onclick="toggleRight()" title="Intelligence">&#9670;</button>
    </div>
  </div>

  <div class="messages-area" id="messages">
    <div class="msg-wrap sys">
      <div class="msg-who">SYSTEM</div>
      <div class="msg-bubble">F.R.I.D.A.Y online. Ready when you are, boss.</div>
    </div>
  </div>

  <div class="input-zone">
    <div class="quick-actions">
      <button class="qa-btn" onclick="quickSend('FRIDAY run a morning brief')">Morning Brief</button>
      <button class="qa-btn" onclick="quickSend('FRIDAY threat assessment')">Threat Scan</button>
      <button class="qa-btn" onclick="quickSend('What is your status')">Status</button>
    </div>

    <div class="input-row">
      <input class="chat-inp" id="chat-inp" placeholder="Say 'FRIDAY' or type here, boss..."
             onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();send()}">
      <input type="file" id="vision-file" accept="image/*" style="display:none" onchange="uploadVisionImage(event)">
      <button class="mic-btn" id="vision-btn" onclick="document.getElementById('vision-file').click()" title="Show FRIDAY something">&#128206;</button>
      <button class="mic-btn" id="mic-btn" onclick="toggleMic()">&#127908;</button>
      <button class="send-btn" onclick="send()">&#9654;</button>
    </div>
    <div class="voice-hint" id="voice-hint" style="display:none;">Listening for "FRIDAY" — say the wake word, then your command.</div>
  </div>

</div>

<button class="status-orb" onclick="toggleLeft()" title="System status">
  <div class="status-orb-dot" id="status-orb-dot"></div>
</button>

<button class="mute-float" id="mute-float" onclick="toggleMute()" title="Mute voice">&#128266;</button>

<script>
const BASE = '';
let muted = false, recording = false;
let currentAudio = null;
let leftOpen = false, rightOpen = false;

(function() {
  const container = document.getElementById('particles');
  for (let i = 0; i < 30; i++) {
    const p = document.createElement('div');
    p.className = 'particle';
    p.style.left = Math.random() * 100 + '%';
    p.style.animationDuration = (8 + Math.random() * 12) + 's';
    p.style.animationDelay = (Math.random() * 10) + 's';
    p.style.opacity = Math.random() * 0.5;
    container.appendChild(p);
  }
})();

function tick() {
  document.getElementById('clock').textContent = new Date().toLocaleTimeString('en-US', {hour12: false});
}
setInterval(tick, 1000); tick();

function toggleLeft() {
  leftOpen = !leftOpen;
  document.getElementById('panel-left').classList.toggle('open', leftOpen);
  document.getElementById('backdrop').classList.toggle('on', leftOpen || rightOpen);
  if (leftOpen && rightOpen) toggleRight();
}
function toggleRight() {
  rightOpen = !rightOpen;
  document.getElementById('panel-right').classList.toggle('open', rightOpen);
  document.getElementById('backdrop').classList.toggle('on', leftOpen || rightOpen);
  if (rightOpen && leftOpen) toggleLeft();
}
function closeAll() {
  leftOpen = rightOpen = false;
  document.getElementById('panel-left').classList.remove('open');
  document.getElementById('panel-right').classList.remove('open');
  document.getElementById('backdrop').classList.remove('on');
}

async function send() {
  const inp = document.getElementById('chat-inp');
  const text = inp.value.trim();
  if (!text) return;
  inp.value = '';
  addMsg('user', 'YOU', text);
  showThinking();
  try {
    const r = await fetch(`${BASE}/command`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({prompt: text}),
    });
    const d = await r.json();
    hideThinking();
    addMsg('fri', 'FRIDAY', d.response || '...', {model: d.model || '', ms: d.ms || 0, emotion: d.emotion});
    showFace();
    if (!muted && d.has_audio && d.audio_file) playAudio(d.audio_file);
  } catch(e) {
    hideThinking();
    addMsg('sys', 'SYSTEM', 'Connection issue, boss.');
  }
}

function quickSend(text) {
  document.getElementById('chat-inp').value = text;
  send();
}

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}

function addMsg(type, label, text, meta = {}) {
  const area = document.getElementById('messages');
  hideThinking();
  const wrap = document.createElement('div');
  wrap.className = `msg-wrap ${type}`;
  const clean = escapeHtml(text)
    .replace(/\\[Confidence:\\s*\\d+%\\]/gi, '')
    .replace(/_FYI:.*?_/gi, '')
    .replace(/\\*\\*(.*?)\\*\\*/g, '<strong>$1</strong>')
    .replace(/\\*(.*?)\\*/g, '<em>$1</em>');
  let metaHtml = '';
  if (meta.model || meta.ms) {
    metaHtml = `<div class="msg-meta">
      ${meta.model ? `<span class="msg-model-badge">${meta.model.toUpperCase().slice(0,20)}</span>` : ''}
      ${meta.ms ? `<span class="msg-ms">${meta.ms}ms</span>` : ''}
      ${meta.emotion && meta.emotion !== 'neutral' ? `<span class="msg-emotion">${meta.emotion}</span>` : ''}
    </div>`;
  }
  wrap.innerHTML = `<div class="msg-who">${label}</div><div class="msg-bubble">${clean}</div>${metaHtml}`;
  area.appendChild(wrap);
  area.scrollTop = area.scrollHeight;
}

let thinkEl = null;
function showThinking() {
  const area = document.getElementById('messages');
  thinkEl = document.createElement('div');
  thinkEl.className = 'thinking-bubble';
  thinkEl.innerHTML = `<div class="think-dots-wrap"><div class="tdot"></div><div class="tdot"></div><div class="tdot"></div></div><span class="thinking-text">FRIDAY IS THINKING</span>`;
  area.appendChild(thinkEl);
  area.scrollTop = area.scrollHeight;
}
function hideThinking() { if (thinkEl) { thinkEl.remove(); thinkEl = null; } }

function playAudio(file) {
  if (muted) return;
  if (currentAudio) { currentAudio.pause(); currentAudio = null; }
  const url = `${BASE}/friday/voice/audio?file=${encodeURIComponent(file)}&t=${Date.now()}`;
  currentAudio = new Audio(url);
  // Same page as the arc reactor canvas, so no server round-trip needed —
  // these real play/ended/pause events are the reactor's actual signal.
  currentAudio.addEventListener('play', () => {
    if (window.onFridaySpeak) window.onFridaySpeak();
    if (window.onFridaySpeakFace) window.onFridaySpeakFace();
  });
  currentAudio.addEventListener('ended', () => {
    if (window.onFridayDone) window.onFridayDone();
    if (window.onFridayDoneFace) window.onFridayDoneFace();
    openConversationWindow();
  });
  currentAudio.addEventListener('pause', () => {
    if (window.onFridayDone) window.onFridayDone();
    if (window.onFridayDoneFace) window.onFridayDoneFace();
  });
  currentAudio.play().catch(() => {});
}

let faceHideTimer = null;
function showFace() {
  const el = document.getElementById('friday-face');
  if (!el) return;
  el.classList.add('on');
  if (faceHideTimer) clearTimeout(faceHideTimer);
  faceHideTimer = setTimeout(() => el.classList.remove('on'), 4000);
}

async function uploadVisionImage(event) {
  const file = event.target.files[0];
  event.target.value = '';
  if (!file) return;
  const reader = new FileReader();
  reader.onload = async () => {
    // reader.result is "data:image/...;base64,XXXX" — strip the prefix,
    // the vision route only wants the raw base64 payload.
    const b64 = reader.result.split(',')[1];
    addMsg('user', 'YOU', `[image: ${file.name}]`);
    showThinking();
    try {
      const r = await fetch(`${BASE}/friday/vision/analyze`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({image: b64, question: ''}),
      });
      const d = await r.json();
      hideThinking();
      addMsg('fri', 'FRIDAY', d.analysis || d.error || "Couldn't make sense of that, boss.");
      showFace();
    } catch (e) {
      hideThinking();
      addMsg('sys', 'SYSTEM', 'Vision analysis failed, boss.');
    }
  };
  reader.readAsDataURL(file);
}

function toggleMute() {
  muted = !muted;
  const btn = document.getElementById('mute-float');
  btn.innerHTML = muted ? '&#128263;' : '&#128266;';
  btn.classList.toggle('on', muted);
  if (muted && currentAudio) currentAudio.pause();
}

function toggleMic() {
  recording = !recording;
  document.getElementById('mic-btn').classList.toggle('on', recording);
}

// ── Wake-word ("FRIDAY") + hands-free command capture ─────────────────────
// Separate from mic-btn/toggleMic() above (that's an unrelated pre-existing
// stub) — this is continuous background listening for the wake word using
// the browser's free Web Speech API, then MediaRecorder to grab the actual
// command as audio and ship it to the server for real Whisper transcription
// (Web Speech's own transcript is unreliable enough across browsers that we
// don't trust it for the command itself, only for wake-word spotting).
const WAKE_WORD = 'friday';
const FOLLOWUP_MS = 6000;
let voiceModeOn = false;
let wakeRecognition = null;
let commandRecorder = null;
let commandChunks = [];
let silenceTimer = null;
let awaitingCommand = false;

function getSpeechRecognition() {
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

// Floating "listening" pill, distinct from the status-orb color change
// beginCommandCapture() already does — a persistent state readable at a
// glance beats scanning the chat log mid-sentence.
function showListeningIndicator(active, symbol) {
  let el = document.getElementById('voice-listening-indicator');
  if (!el) {
    el = document.createElement('div');
    el.id = 'voice-listening-indicator';
    el.style.cssText = `
      position: fixed; top: 70px; left: 50%; transform: translateX(-50%);
      padding: 8px 20px; border-radius: 20px; font-size: 11px;
      letter-spacing: 2px; z-index: 100; display: none;
      backdrop-filter: blur(10px); transition: all 0.2s;
    `;
    document.body.appendChild(el);
  }
  if (!active) { el.style.display = 'none'; return; }
  el.style.display = 'block';
  if (symbol === '?') {
    el.style.background = 'rgba(255,204,0,0.15)';
    el.style.border = '1px solid rgba(255,204,0,0.4)';
    el.style.color = '#ffcc00';
    el.textContent = '? DID YOU MEAN ME?';
  } else {
    el.style.background = 'rgba(72,202,228,0.15)';
    el.style.border = '1px solid rgba(72,202,228,0.4)';
    el.style.color = '#48cae4';
    el.textContent = '● LISTENING...';
  }
}

// Local browser TTS for an instant ack on ambiguous wake-word detections —
// no server round trip for a reflexive "Yes, boss?".
function speakQuick(text) {
  try {
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1.1; u.volume = 0.8;
    window.speechSynthesis.speak(u);
  } catch (e) {}
}

function toggleVoiceMode() {
  const SR = getSpeechRecognition();
  if (!SR) {
    addMsg('sys', 'SYSTEM', "This browser doesn't support wake-word listening, boss.");
    return;
  }
  voiceModeOn = !voiceModeOn;
  const btn = document.getElementById('voice-mode-btn');
  btn.textContent = voiceModeOn ? 'VOICE ON' : 'VOICE OFF';
  btn.classList.toggle('on', voiceModeOn);
  document.getElementById('voice-hint').style.display = voiceModeOn ? 'block' : 'none';
  if (voiceModeOn) startWakeListening();
  else stopWakeListening();
}

function startWakeListening() {
  const SR = getSpeechRecognition();
  wakeRecognition = new SR();
  wakeRecognition.continuous = true;
  wakeRecognition.interimResults = true;
  wakeRecognition.lang = 'en-US';

  wakeRecognition.onresult = (event) => {
    if (awaitingCommand) return;
    const last = event.results[event.results.length - 1];
    const transcript = Array.from(event.results)
      .map(r => r[0].transcript)
      .join(' ')
      .toLowerCase();
    if (!transcript.includes(WAKE_WORD)) return;

    // confidence is 0/unset on some browsers for interim results — treat
    // that the same as high confidence rather than silently dropping every
    // wake word on browsers that don't report it.
    const confidence = last[0].confidence || 0;
    if (confidence > 0 && confidence < 0.35) return; // background noise — ignored

    if (confidence > 0 && confidence < 0.65) {
      beginCommandCapture(true);
    } else {
      beginCommandCapture(false);
    }
  };

  // Web Speech recognizers stop themselves periodically (silence, browser
  // policy, etc.) — restart automatically so "continuous" listening actually
  // stays continuous while VOICE ON is toggled on.
  wakeRecognition.onend = () => {
    if (voiceModeOn && !awaitingCommand) {
      try { wakeRecognition.start(); } catch (e) {}
    }
  };
  wakeRecognition.onerror = () => {
    if (voiceModeOn && !awaitingCommand) {
      try { wakeRecognition.start(); } catch (e) {}
    }
  };

  try { wakeRecognition.start(); } catch (e) {}
}

function stopWakeListening() {
  awaitingCommand = false;
  if (wakeRecognition) {
    wakeRecognition.onend = null;
    wakeRecognition.onerror = null;
    try { wakeRecognition.stop(); } catch (e) {}
    wakeRecognition = null;
  }
  if (commandRecorder && commandRecorder.state !== 'inactive') {
    try { commandRecorder.stop(); } catch (e) {}
  }
  clearTimeout(silenceTimer);
}

async function beginCommandCapture(ambiguous, timeoutMs) {
  if (awaitingCommand) return;
  awaitingCommand = true;
  try { wakeRecognition.stop(); } catch (e) {}

  // Interrupt: wake word heard mid-response means "stop talking, I'm
  // talking to you now" — harmless to call when nothing is playing.
  if (currentAudio && !currentAudio.paused) { currentAudio.pause(); currentAudio.currentTime = 0; }
  try { window.speechSynthesis.cancel(); } catch (e) {}

  if (ambiguous) {
    showListeningIndicator(true, '?');
    speakQuick('Yes, boss?');
  } else {
    showListeningIndicator(true, '●');
  }
  document.getElementById('status-orb-dot').style.background = 'var(--warn)';

  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    addMsg('sys', 'SYSTEM', "Couldn't access the microphone, boss.");
    showListeningIndicator(false);
    awaitingCommand = false;
    if (voiceModeOn) try { wakeRecognition.start(); } catch (e2) {}
    return;
  }

  commandChunks = [];
  commandRecorder = new MediaRecorder(stream);
  commandRecorder.ondataavailable = (e) => { if (e.data.size > 0) commandChunks.push(e.data); };
  commandRecorder.onstop = async () => {
    stream.getTracks().forEach(t => t.stop());
    clearTimeout(silenceTimer);
    showListeningIndicator(false);
    const blob = new Blob(commandChunks, { type: 'audio/webm' });
    await sendCommandAudio(blob);
    awaitingCommand = false;
    if (voiceModeOn) { try { wakeRecognition.start(); } catch (e) {} }
  };

  commandRecorder.start();
  resetSilenceTimer(timeoutMs);
}

function resetSilenceTimer(timeoutMs) {
  clearTimeout(silenceTimer);
  // 2.5s of silence after the wake word = "the command is done" by default
  // (no reliable cross-browser voice-activity signal to key off of); the
  // follow-up conversation window below passes a longer timeout instead.
  silenceTimer = setTimeout(() => {
    if (commandRecorder && commandRecorder.state !== 'inactive') commandRecorder.stop();
  }, timeoutMs || 2500);
}

// ── Conversation continuity ─────────────────────────────────────────────────
// After FRIDAY finishes speaking, keep listening briefly without requiring
// the wake word again, so "and what about tomorrow" works as a natural
// follow-up instead of every turn needing "friday" repeated.
function openConversationWindow() {
  if (!voiceModeOn || awaitingCommand) return;
  beginCommandCapture(false, FOLLOWUP_MS);
}

async function sendCommandAudio(blob) {
  if (blob.size < 500) return; // near-empty capture (e.g. an unanswered follow-up window) — not worth a transcribe call
  const form = new FormData();
  form.append('audio', blob, 'command.webm');
  try {
    const r = await fetch(`${BASE}/friday/voice/transcribe`, { method: 'POST', body: form });
    const d = await r.json();
    // Confirmed non-enrolled speaker (TV, another person) — stay silent,
    // not an error: this is what actually stops background audio from
    // hijacking the conversation continuity window.
    if (d.rejected) return;
    let text = (d.text || '').trim();
    if (!text) return;
    // Strip a leading wake word so "friday what's my status" becomes
    // "what's my status" before it hits the normal send() path.
    const wakeRe = new RegExp(`^\\s*${WAKE_WORD}\\s*[,:]?\\s*`, 'i');
    text = text.replace(wakeRe, '').trim();
    if (!text) return;
    document.getElementById('chat-inp').value = text;
    send();
  } catch (e) {
    addMsg('sys', 'SYSTEM', 'Voice transcription failed, boss.');
  }
}

// ── Voice enrollment ─────────────────────────────────────────────────────────
// Five ~3.5s samples (rather than one) give Resemblyzer enough voiceprint
// variety to set a usable match threshold on the bridge side.
// Enrollment state lives across separate clicks (one click = one sample,
// no auto-continue) — a prior version looped all 5 samples automatically
// inside one call with the button never disabled, so a single impatient
// re-click mid-loop spawned a second concurrent enrollVoice() run; with
// two loops racing, 28 POSTs in under a minute (instead of 5) was the
// observed result, each capturing whatever partial/garbage audio was
// mid-flight at the moment of the second click.
let enrollSampleCount = 0;
let enrollInFlight = false;
const ENROLL_TARGET = 5;
const ENROLL_SAMPLE_MS = 3500;

async function enrollVoice() {
  const btn = document.getElementById('enroll-voice-btn');
  if (enrollInFlight || enrollSampleCount >= ENROLL_TARGET) return;
  enrollInFlight = true;
  btn.disabled = true;

  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    btn.textContent = '⚠ MIC ACCESS DENIED';
    enrollInFlight = false;
    btn.disabled = false;
    return;
  }

  const chunks = [];
  const recorder = new MediaRecorder(stream);
  recorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
  const recordingDone = new Promise((resolve) => { recorder.onstop = resolve; });

  // Visible countdown — unambiguous "safe to speak now" vs "done, uploading".
  let remaining = Math.round(ENROLL_SAMPLE_MS / 1000);
  btn.textContent = `🔴 RECORDING... ${remaining}`;
  const countdown = setInterval(() => {
    remaining -= 1;
    if (remaining > 0) btn.textContent = `🔴 RECORDING... ${remaining}`;
  }, 1000);

  recorder.start();
  await new Promise((resolve) => setTimeout(resolve, ENROLL_SAMPLE_MS));
  recorder.stop();
  await recordingDone;
  clearInterval(countdown);
  stream.getTracks().forEach(t => t.stop());

  btn.textContent = '⏳ Uploading...';
  const blob = new Blob(chunks, { type: 'audio/webm' });
  const form = new FormData();
  form.append('audio', blob, 'enroll.webm');
  form.append('profile', 'default');

  try {
    const r = await fetch(`${BASE}/friday/voice/enroll`, { method: 'POST', body: form });
    const d = await r.json();
    if (!r.ok || d.error) {
      btn.textContent = '⚠ ERROR — CLICK TO RETRY';
      enrollInFlight = false;
      btn.disabled = false;
      return;
    }
    // Trust the server's real count over a local increment — if a
    // request genuinely failed to register server-side, the two could
    // otherwise drift apart silently.
    enrollSampleCount = d.sample_count || enrollSampleCount + 1;
  } catch (e) {
    btn.textContent = '⚠ ERROR — CLICK TO RETRY';
    enrollInFlight = false;
    btn.disabled = false;
    return;
  }

  enrollInFlight = false;
  if (enrollSampleCount >= ENROLL_TARGET) {
    btn.textContent = '✓ VOICE ENROLLED';
    btn.disabled = true; // permanent — no more samples needed
  } else {
    btn.textContent = `🎤 ENROLL MY VOICE (${enrollSampleCount}/${ENROLL_TARGET}) — CLICK TO CONTINUE`;
    btn.disabled = false;
  }
}

async function setMode(mode) {
  document.querySelectorAll('.mode-btn').forEach(b => {
    b.classList.toggle('active', b.textContent.toLowerCase() === mode);
  });
  await fetch(`${BASE}/mode`, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({mode}),
  }).catch(() => {});
}

async function runProto(n) {
  const r = await fetch(`${BASE}/friday/protocols/${n}`, {method: 'POST'}).catch(() => null);
  if (r && r.ok) {
    const d = await r.json();
    addMsg('sys', 'SYSTEM', `Protocol ${n}: ${d.name || d.status || 'executed'}.`);
  }
}

async function pollState() {
  try {
    const r = await fetch(`${BASE}/state`);
    const d = await r.json();

    const pill = document.getElementById('status-pill');
    if (d.status === 'online') { pill.textContent = 'ONLINE'; pill.className = 'pill online'; }
    else { pill.textContent = 'DEGRADED'; pill.className = 'pill warn'; }

    const jp = document.getElementById('jarvis-pill');
    jp.textContent = d.jarvis_online ? 'JARVIS ON' : 'JARVIS OFF';
    jp.className = d.jarvis_online ? 'pill online' : 'pill warn';

    document.getElementById('cov-banner').className = d.coverage_mode ? 'cov-banner on' : 'cov-banner';
    document.getElementById('model-pill').textContent = (d.voice_mode || 'normal').toUpperCase();
    document.getElementById('status-orb-dot').style.background = d.status === 'online' ? 'var(--green)' : 'var(--warn)';

    const up = d.uptime || 0;
    const h = Math.floor(up/3600), m = Math.floor((up%3600)/60);
    document.getElementById('p-uptime').textContent = h ? `${h}h ${m}m` : `${m}m`;
    document.getElementById('p-jarvis').textContent = d.jarvis_online ? 'ONLINE' : 'OFFLINE';
    document.getElementById('p-jarvis').className = 'info-val ' + (d.jarvis_online ? 'green' : 'danger');
    document.getElementById('p-coverage').textContent = d.coverage_mode ? 'ACTIVE' : 'STANDBY';
    document.getElementById('p-mode').textContent = (d.voice_mode || 'normal').toUpperCase();

    const b = d.budget || {};
    document.getElementById('p-calls').textContent = `${b.calls||0} / ${b.calls_limit||'-'}`;

    if (d.cpu_pct !== undefined && d.cpu_pct !== null) {
      document.getElementById('p-cpu').textContent = `${d.cpu_pct}%`;
      document.getElementById('p-cpu-bar').style.width = `${d.cpu_pct}%`;
    }
    if (d.ram_pct !== undefined && d.ram_pct !== null) {
      document.getElementById('p-ram').textContent = `${d.ram_pct}%`;
      document.getElementById('p-ram-bar').style.width = `${d.ram_pct}%`;
      document.getElementById('p-ram-bar').className = d.ram_pct > 80 ? 'stat-bar-fill warn' : 'stat-bar-fill';
    }

    const sec = d.security || {};
    document.getElementById('p-threats').textContent = sec.threats || 0;
    document.getElementById('p-blocked').textContent = sec.blocked_ips || 0;

    const training = d.training || {};
    document.getElementById('p-training').textContent = training.facts_learned !== undefined ? training.facts_learned : '-';

    const trend = d.emotional_trend || {};
    if (Object.keys(trend).length) {
      document.getElementById('p-emotions').innerHTML = Object.entries(trend)
        .sort((a,b) => b[1]-a[1]).slice(0,5)
        .map(([e,c]) => `<div class="emotion-badge">${e} (${c})</div>`).join('');
    }
  } catch(e) {
    document.getElementById('status-pill').className = 'pill warn';
  }
}

async function pollVeronica() {
  try {
    const r = await fetch(`${BASE}/friday/veronica/status`);
    const d = await r.json();
    document.getElementById('v-backed').textContent = d.components_backed_up !== undefined ? d.components_backed_up : '-';
    document.getElementById('v-repairs').textContent = d.repairs_performed || 0;
  } catch(e) {}
}

async function pollTrust() {
  try {
    const r = await fetch(`${BASE}/friday/trust`);
    const d = await r.json();
    document.getElementById('trust-tier').textContent = (d.tier || '-').replace('_', ' ').toUpperCase();
    document.getElementById('trust-bar').style.width = `${d.trust || 0}%`;
  } catch(e) {}
}

pollState();
pollVeronica();
pollTrust();
setInterval(pollState, 5000);
setInterval(pollVeronica, 30000);
setInterval(pollTrust, 30000);
document.getElementById('chat-inp').focus();

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeAll();
  if (e.ctrlKey && e.key === '/') { document.getElementById('chat-inp').focus(); e.preventDefault(); }
});

// FRIDAY arc reactor (blue tinted) — voice-reactive: surges when she
// speaks. window.onFridaySpeak/onFridayDone are called from playAudio()'s
// real Audio play/ended/pause listeners above, same page, no server
// round-trip needed (unlike JARVIS's globe, FRIDAY's HUD has no separate
// page that needs cross-window sync).
(function() {
  const c   = document.getElementById('friday-arc');
  if (!c) return;
  const ctx = c.getContext('2d');
  const W = 32, H = 32, CX = 16, CY = 16;
  let t = 0;
  let speakIntensity = 0;
  let speaking = false;

  window.onFridaySpeak = function() {
    speaking = true;
    speakIntensity = 0;
  };
  window.onFridayDone = function() {
    speaking = false;
  };

  function drawFriday() {
    ctx.clearRect(0, 0, W, H);

    if (speaking) speakIntensity = Math.min(1, speakIntensity + 0.08);
    else          speakIntensity = Math.max(0, speakIntensity - 0.04);

    const glow  = 0.5 + Math.sin(t * 2) * 0.3 + speakIntensity * 0.5;
    const speed = 1 + speakIntensity * 4;

    // Outer ring
    ctx.beginPath();
    ctx.arc(CX, CY, 14, 0, Math.PI * 2);
    ctx.strokeStyle = `rgba(72,202,228,${glow * 0.8})`;
    ctx.lineWidth   = speaking ? 2 : 1.5;
    ctx.shadowColor = '#00b4d8';
    ctx.shadowBlur  = speaking ? 8 * speakIntensity : 0;
    ctx.stroke();
    ctx.shadowBlur  = 0;

    ctx.save();
    ctx.translate(CX, CY);
    ctx.rotate(t * 0.5 * speed);
    for (let i = 0; i < 6; i++) {
      const a1 = (i/6)*Math.PI*2;
      const a2 = a1 + Math.PI/6*(0.7 + speakIntensity*0.3);
      ctx.beginPath();
      ctx.arc(0, 0, 10, a1, a2);
      ctx.strokeStyle = `rgba(0,180,216,${glow*0.7})`;
      ctx.lineWidth   = 2 + speakIntensity * 1.5;
      ctx.stroke();
    }
    ctx.restore();

    ctx.save();
    ctx.translate(CX, CY);
    ctx.rotate(-t * 0.8 * speed);
    for (let i = 0; i < 4; i++) {
      const a1 = (i/4)*Math.PI*2;
      const a2 = a1 + Math.PI/4*(0.6 + speakIntensity*0.4);
      ctx.beginPath();
      ctx.arc(0, 0, 7, a1, a2);
      ctx.strokeStyle = `rgba(0,150,199,${glow*0.6})`;
      ctx.lineWidth   = 1.5 + speakIntensity;
      ctx.stroke();
    }
    ctx.restore();

    // Blue triangle core
    ctx.save();
    ctx.translate(CX, CY);
    ctx.rotate(t * 0.1 * speed);
    const ts = 1 + speakIntensity * 0.3;
    ctx.scale(ts, ts);
    ctx.beginPath();
    for (let i = 0; i < 3; i++) {
      const angle = (i/3)*Math.PI*2 - Math.PI/6;
      const x = Math.cos(angle)*5;
      const y = Math.sin(angle)*5;
      if (i===0) ctx.moveTo(x,y);
      else ctx.lineTo(x,y);
    }
    ctx.closePath();
    ctx.strokeStyle = `rgba(144,224,239,${glow*0.9})`;
    ctx.lineWidth   = 1.5 + speakIntensity;
    ctx.shadowColor = '#48cae4';
    ctx.shadowBlur  = speakIntensity * 6;
    ctx.stroke();
    ctx.shadowBlur  = 0;
    ctx.restore();

    // Blue center glow
    const sz = 4 + speakIntensity * 3;
    const cg = ctx.createRadialGradient(CX,CY,0,CX,CY,sz);
    cg.addColorStop(0, `rgba(200,240,255,${glow})`);
    cg.addColorStop(0.5, `rgba(72,202,228,${glow*0.6})`);
    cg.addColorStop(1, 'rgba(0,168,255,0)');
    ctx.beginPath();
    ctx.arc(CX, CY, sz, 0, Math.PI*2);
    ctx.fillStyle = cg;
    ctx.fill();

    // Pulse ring while speaking
    if (speaking && Math.sin(t * 8) > 0.7) {
      ctx.beginPath();
      ctx.arc(CX, CY, 14 + speakIntensity * 4, 0, Math.PI*2);
      ctx.strokeStyle = `rgba(72,202,228,${speakIntensity * 0.3})`;
      ctx.lineWidth   = 1;
      ctx.stroke();
    }

    t += 0.015;
    requestAnimationFrame(drawFriday);
  }
  drawFriday();
})();

// Holographic face — a separate canvas from friday-arc (that one stays the
// small top-bar reactor); this one is the big centered projection that
// fades in on every response via showFace() above. Kept intentionally
// simple (arcs + lines, no image assets) since it redraws every frame on
// every page load, not just while actively speaking.
(function() {
  const c = document.getElementById('friday-face');
  if (!c) return;
  const ctx = c.getContext('2d');
  const W = 220, H = 220, CX = 110, CY = 100;
  let t = 0;
  let speaking = false;
  let mouthOpen = 0;

  window.onFridaySpeakFace = function() { speaking = true; };
  window.onFridayDoneFace = function() { speaking = false; };

  function drawFace() {
    ctx.clearRect(0, 0, W, H);

    // Jaw / face outline — an open hexagonal contour, not a closed mask,
    // so it reads as a HUD wireframe rather than a solid head.
    ctx.beginPath();
    ctx.moveTo(CX - 55, CY - 40);
    ctx.lineTo(CX - 60, CY + 10);
    ctx.lineTo(CX - 35, CY + 55);
    ctx.lineTo(CX, CY + 70);
    ctx.lineTo(CX + 35, CY + 55);
    ctx.lineTo(CX + 60, CY + 10);
    ctx.lineTo(CX + 55, CY - 40);
    ctx.strokeStyle = 'rgba(72,202,228,0.45)';
    ctx.lineWidth = 1.2;
    ctx.stroke();

    // Scan lines — slow vertical sweep across the face box.
    const scanY = CY - 70 + ((t * 20) % 150);
    ctx.beginPath();
    ctx.moveTo(CX - 65, scanY);
    ctx.lineTo(CX + 65, scanY);
    ctx.strokeStyle = 'rgba(72,202,228,0.15)';
    ctx.lineWidth = 1;
    ctx.stroke();

    // Eyes — glow pulses gently at rest, brighter and slightly wider while
    // speaking so the face doesn't look inert during a response.
    const glow = 0.55 + Math.sin(t * 2) * 0.25 + (speaking ? 0.2 : 0);
    for (const ex of [CX - 22, CX + 22]) {
      const grad = ctx.createRadialGradient(ex, CY - 5, 0, ex, CY - 5, 9);
      grad.addColorStop(0, `rgba(210,245,255,${glow})`);
      grad.addColorStop(0.5, `rgba(72,202,228,${glow * 0.7})`);
      grad.addColorStop(1, 'rgba(0,168,255,0)');
      ctx.beginPath();
      ctx.arc(ex, CY - 5, 9, 0, Math.PI * 2);
      ctx.fillStyle = grad;
      ctx.fill();

      ctx.beginPath();
      ctx.arc(ex, CY - 5, 3, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(255,255,255,${glow})`;
      ctx.fill();
    }

    // Mouth — only animates while speaking; otherwise settles to a flat
    // line so the face doesn't look like it's talking when it isn't.
    if (speaking) mouthOpen = Math.max(0.15, (Math.sin(t * 14) + 1) / 2);
    else mouthOpen = Math.max(0, mouthOpen - 0.08);

    ctx.beginPath();
    ctx.ellipse(CX, CY + 35, 16, 2 + mouthOpen * 8, 0, 0, Math.PI * 2);
    ctx.strokeStyle = `rgba(144,224,239,${0.6 + mouthOpen * 0.4})`;
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Small data readout — flavor text, not real telemetry.
    ctx.font = '8px monospace';
    ctx.fillStyle = 'rgba(72,202,228,0.5)';
    ctx.fillText(speaking ? 'VOICE: ACTIVE' : 'STANDBY', CX - 60, CY + 90);
    ctx.fillText(`T+${Math.floor(t)}`, CX + 30, CY + 90);

    t += 0.03;
    requestAnimationFrame(drawFace);
  }
  drawFace();
})();
</script>
</body>
</html>
"""

# ── Entry ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logging.info(f"FRIDAY V2 starting on port {port}")
    app.run(host="0.0.0.0", port=port)
