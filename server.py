"""FRIDAY V2 — complete server. Flask + emotional intelligence + JARVIS
monitoring + green HUD + voice-mode control."""
import time
from flask import Flask, jsonify, redirect
from werkzeug.middleware.proxy_fix import ProxyFix

# app + /health come before anything else that could fail to import or
# block — Railway's healthcheck needs a fast 200 from this path to keep
# the deploy alive at all, and gunicorn can't serve *any* route until
# this module finishes importing top to bottom. A single broken import
# further down (or in a nested core/ module) previously meant the whole
# app never came up, independent of how fast /health's own handler is.
app = Flask(__name__)

# Render/Railway both put exactly one reverse proxy in front of this app,
# so request.remote_addr (and request.scheme) would otherwise always
# report the proxy, not the real client — which is why
# services/friday_security.py used to hand-parse X-Forwarded-For itself,
# trusting whatever IP showed up first. That's spoofable: a client can
# set their own X-Forwarded-For with a fake address prepended, and if the
# proxy appends rather than replaces the header, the fake entry — not
# Render/Railway's real one — is what "first" picks up. ProxyFix(x_for=1)
# instead trusts exactly one hop counted from the right (the proxy's own
# addition), which a client can't forge from outside it. x_for/x_proto
# only — x_host/x_port/x_prefix stay at 0 since nothing here needs the
# Host header rewritten.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=0, x_port=0, x_prefix=0)

BOOT_TIME = time.time()


@app.route("/health")
def health():
    return "OK", 200


from core import access_auth

_LOGIN_PAGE_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>F.R.I.D.A.Y — Access</title>
<style>
  body { background:#000814; color:#caf0f8; font-family:-apple-system,'SF Pro Display','Helvetica Neue',sans-serif;
    height:100vh; height:100dvh; display:flex; align-items:center; justify-content:center; margin:0; }
  form { background:rgba(0,150,199,0.06); border:1px solid rgba(72,202,228,0.2); border-radius:16px;
    padding:32px 28px; width:min(320px, 88vw); backdrop-filter:blur(20px); }
  h1 { font-size:14px; letter-spacing:6px; color:#48cae4; margin:0 0 20px; text-align:center; }
  input { width:100%; box-sizing:border-box; background:rgba(0,150,199,0.12); border:1px solid rgba(72,202,228,0.2);
    border-radius:10px; padding:12px 14px; color:#caf0f8; font-size:15px; outline:none; margin-bottom:14px; }
  input:focus { border-color:rgba(72,202,228,0.5); }
  button { width:100%; background:linear-gradient(135deg,#0096c7,#48cae4); color:#000814; border:none;
    border-radius:10px; padding:12px; font-size:14px; font-weight:600; letter-spacing:1px; cursor:pointer; }
  .err { color:#e63946; font-size:12px; margin:-6px 0 14px; text-align:center; }
</style></head>
<body>
<form method="POST" action="/login?next=__NEXT_PATH__">
  <h1>F.R.I.D.A.Y</h1>
  __ERROR_HTML__
  <input type="password" name="token" placeholder="Access token" autofocus autocomplete="current-password">
  <button type="submit">Enter</button>
</form>
</body></html>"""


def _render_login_page(next_path: str, error_html: str = "") -> str:
    # .format() would choke on every literal `{...}` in the <style>
    # block above (it's not just my two placeholders) — plain .replace()
    # on unique tokens sidesteps that instead of escaping every CSS brace.
    return _LOGIN_PAGE_HTML.replace("__NEXT_PATH__", next_path).replace("__ERROR_HTML__", error_html)


@app.before_request
def _check_access():
    if not access_auth.is_configured():
        return  # not set up yet — config_validator flags this; don't lock the boss out before he's configured it
    if access_auth.is_exempt(request.path):
        return
    if access_auth.has_valid_session(request.cookies.get(access_auth.SESSION_COOKIE, "")):
        return
    header_token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if access_auth.check_token(header_token) or access_auth.check_token(request.args.get("token", "")):
        return
    if request.path == "/hud":
        return redirect(f"/login?next={request.path}")
    return jsonify({"error": "Unauthorized"}), 401


@app.route("/login", methods=["GET", "POST"])
def login():
    if not access_auth.is_configured():
        return jsonify({"error": "FRIDAY_ACCESS_TOKEN not configured"}), 503

    next_path = request.args.get("next", "/hud")
    # "//evil.com" passes a bare startswith("/") check but browsers treat
    # it as a protocol-relative external URL — the actual open-redirect
    # shape to guard against, not just a non-leading-slash value. Checking
    # the backslash-normalized path (not next_path itself) closes the
    # same bypass via "/\evil.com": WHATWG URL parsing treats \ as / for
    # http(s) links, so browsers resolve that identically to "//evil.com"
    # even though the raw string only has one leading slash.
    if not next_path.startswith("/") or next_path.replace("\\", "/").startswith("//"):
        next_path = "/hud"

    if request.method == "GET":
        return Response(_render_login_page(next_path), mimetype="text/html")

    data = request.form or request.get_json(silent=True) or {}
    token = data.get("token", "")
    if not access_auth.check_token(token):
        return Response(
            _render_login_page(next_path, '<div class="err">Wrong token, boss.</div>'),
            mimetype="text/html",
        ), 401

    resp = redirect(next_path)
    resp.set_cookie(
        access_auth.SESSION_COOKIE, access_auth.session_cookie_value(),
        httponly=True, secure=True, samesite="Lax", max_age=60 * 60 * 24 * 30,
    )
    return resp


import os
import re
import json
import datetime
import logging
import threading
from flask import request, Response

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


logging.basicConfig(level=logging.INFO, format='[FRIDAY] %(message)s')

# Display-only identity — distinct from config/friday_personality.py,
# which is who FRIDAY *is* (her actual character, baked into every LLM
# call). These two just control what shows up in status output and the
# startup log; changing them doesn't touch her personality at all.
FRIDAY_NAME = os.getenv("FRIDAY_NAME", "FRIDAY")
FRIDAY_VERSION = os.getenv("FRIDAY_VERSION", "2.0")


@app.errorhandler(Exception)
def _handle_uncaught_error(e):
    """Before this, an uncaught bug just disappeared into Render's logs
    with nothing surfacing it — the only way to learn something crashed
    was to notice FRIDAY acting wrong. Werkzeug's own HTTPException
    subclasses (404s, a stray 405) pass through untouched — those are
    normal HTTP responses, not bugs worth an alert."""
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e
    logging.exception(f"Unhandled error on {request.path}")
    try:
        from core.error_alerts import report
        report(request.path, e)
    except Exception:
        pass
    return jsonify({"error": "Something went wrong, boss."}), 500


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


# ── Shared state (see core/app_state.py) ──────────────────────────────────
from core.app_state import *  # noqa: F401,F403 -- see core/app_state.py's
# docstring: /command and this file's own startup/background-thread code
# below reference these exact names unchanged from before the blueprint split.

# _ensure_memory() needs BASE_DIR, which now lives in core.app_state --
# must run after the star-import above, not before it. Calling it before
# BASE_DIR exists doesn't raise visibly: the NameError is caught by this
# function's own try/except and only shows up as a logged warning, so
# every directory here would silently never get created.
_ensure_memory()

# ── Blueprints (see routes/*.py) ────────────────────────────────────────────
from routes.voice_vision import voice_vision_bp
from routes.phone import phone_bp
from routes.orchestration import orchestration_bp
from routes.security import security_bp
from routes.health_medicine import health_medicine_bp
from routes.contacts_team import contacts_team_bp
from routes.knowledge import knowledge_bp
from routes.tasks_workouts import tasks_workouts_bp
from routes.email import email_bp
from routes.goals import goals_bp
from routes.spotify_calendar import spotify_calendar_bp
from routes.habits_journal import habits_journal_bp
from routes.reasoning import reasoning_bp
from routes.emcon_scenarios import emcon_scenarios_bp
from routes.life_admin import life_admin_bp
from routes.hud_page import hud_page_bp
from routes.offline import offline_bp

app.register_blueprint(voice_vision_bp)
app.register_blueprint(phone_bp)
app.register_blueprint(orchestration_bp)
app.register_blueprint(security_bp)
app.register_blueprint(health_medicine_bp)
app.register_blueprint(contacts_team_bp)
app.register_blueprint(knowledge_bp)
app.register_blueprint(tasks_workouts_bp)
app.register_blueprint(email_bp)
app.register_blueprint(goals_bp)
app.register_blueprint(spotify_calendar_bp)
app.register_blueprint(habits_journal_bp)
app.register_blueprint(reasoning_bp)
app.register_blueprint(emcon_scenarios_bp)
app.register_blueprint(life_admin_bp)
app.register_blueprint(hud_page_bp)
app.register_blueprint(offline_bp)

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
    try:
        from services.notifications import alert
        alert("JARVIS Offline", "FRIDAY has assumed control.")
    except Exception as e:
        logging.warning(f"JARVIS-down notify failed: {e}")


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
                    from services.notifications import Priority
                    _push("Morning Brief", response, Priority.WARNING)
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

# Unlike CALL_TRIGGERS (which just hands the HUD an "action": "call" for
# the device's own dialer), this fires a real, billable Twilio SMS
# straight from command() — so it's kept to explicit "text"-as-verb
# phrasing rather than CALL_TRIGGERS' broader "call "/"dial " style. A
# false match here still can't send anything real unless the recipient
# resolves to an actual number (MY_PHONE_NUMBER for "text me", or a
# contact with a stored phone) — see the SMS_TRIGGERS handler below.
SMS_TRIGGERS = [
    "text me", "send me a text", "send a text to",
    "shoot a text to", "text ",
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
    # "gmail" appeared in no trigger list at all, and neither did "read
    # my ...", so "Can you read my Gmail" fell through every dispatcher
    # to the plain conversational model -- which answered "I'm not able
    # to access your Gmail account" (confirmed live). That's the #16
    # failure inverted: not a fabricated claim that something happened,
    # but a fabricated claim that a working capability doesn't exist.
    # The model has no idea what FRIDAY can actually do, so anything
    # that misses a trigger risks it confidently denying a real feature.
    # Safe to add here: _cmd_email_summary dispatches after compose/send,
    # so "send an email to my gmail" still reaches the sender first.
    "read my gmail", "check my gmail", "my gmail", "read my email",
    "read my mail", "read my inbox",
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

# Same pending-follow-up shape as _pending_compose_send above, and the
# same reason: "wasn't sure what to schedule there -- try again with a
# time?" invites a bare reply ("3pm tomorrow") that carries none of
# CALENDAR_ADD_TRIGGERS' phrases. Without this, that reply falls through
# to the plain conversational model, which can describe "scheduling" the
# event in prose without ever calling create_event().
_pending_calendar_add: dict = {}
CALENDAR_ADD_PENDING_WINDOW = 300  # seconds

DRAFT_TRIGGERS = [
    "draft a reply", "reply to",
    "write a reply", "respond to",
    "draft email", "write email to",
]

# Confirms and actually sends whatever draft_reply() last produced —
# checked ahead of DRAFT_TRIGGERS's "reply to"/"respond to" would never
# match these short confirmation phrases anyway, but it belongs in the
# same neighborhood: this is step two of that flow, not a new one.
SEND_TRIGGERS = [
    "send it", "send that", "go ahead and send",
    "yes send it", "yes, send it", "send the reply",
    "send that email", "send this email", "send the draft",
]

# Compose-and-send in one shot, no draft/approval step first — distinct
# from DRAFT_TRIGGERS's "write email to" (which only ever drafts). Every
# phrase here starts with "send"/"email" + an explicit target, so none of
# them collide with EMAIL_TRIGGERS' inbox-summary phrases ("check my
# email", "what emails") — still checked first regardless, same reasoning
# as TRIAGE_TRIGGERS below.
COMPOSE_SEND_TRIGGERS = [
    "send an email to", "send email to",
    "compose an email to", "shoot an email to",
    "fire off an email to",
]

# Follow-up state for compose-send's own clarifying question ("who's it
# going to, and what should it say"). Without this, a reply that answers
# that question ("jane@x.com, tell her I'm running late") carries none of
# COMPOSE_SEND_TRIGGERS' phrases, falls through every dispatcher below,
# and lands on the plain conversational model -- which happily describes
# "sending" the email in prose without ever calling send_email(). That's
# not a wording bug, it's FRIDAY claiming to have done something she
# didn't do. Tracking the incomplete attempt for a short window lets the
# very next ambiguous-looking reply get folded back into the real flow
# instead of becoming a fabricated confirmation.
_pending_compose_send: dict = {}
COMPOSE_SEND_PENDING_WINDOW = 300  # seconds -- long enough for a natural pause replying to "who's it going to", short enough not to hijack an unrelated later message indefinitely
CANCEL_TRIGGERS = ["never mind", "nevermind", "cancel that", "forget it", "cancel it"]

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

FILE_TRIGGERS = [
    "create a file", "make a file",
    "create a document", "make a document",
    "write a file", "generate a file",
]

FILE_RECALL_TRIGGERS = [
    "open the file", "show me the file",
    "get the file", "pull up the file",
    "find the file", "resend the file",
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

# SPOTIFY_PLAY_TRIGGERS' "put on" is a substring of both "put on my
# calendar" and "put on my list", and Spotify is checked well before
# calendar and tasks in command()'s dispatch chain -- so without this,
# "put on my calendar September 1st" got treated as a music request and
# came back "Spotify not authenticated" (confirmed live on a real
# device), and "put on my list" was silently broken the same way.
#
# Computed rather than hardcoded so a phrase added to either list later
# is protected automatically: the failure mode here is a command
# silently doing something unrelated, which is exactly the kind of thing
# nobody thinks to re-check when adding a trigger. Reordering the
# dispatch chain would fix today's two collisions but not the general
# shape -- the vaguer trigger would still swallow whatever came after
# it. This makes the vague one yield to the specific one regardless of
# order.
_SPOTIFY_SHADOWED_TRIGGERS = [
    t for t in (CALENDAR_ADD_TRIGGERS + TASK_ADD_TRIGGERS)
    if any(s in t for s in SPOTIFY_PLAY_TRIGGERS + SPOTIFY_STOP_TRIGGERS)
]

TASK_SHOW_TRIGGERS = [
    "what's on my list", "show my tasks",
    "what do i need to do", "my todo",
    "pending tasks", "what's pending",
]

MED_ADD_TRIGGERS = [
    "add medicine", "track my medicine", "remind me to take",
    "i take", "add my medication", "track medication",
]
# Same shadowing shape as _SPOTIFY_SHADOWED_TRIGGERS above, found by
# checking every trigger list against every other in dispatch order:
# REMINDER_TRIGGERS' "remind me" is a substring of MED_ADD_TRIGGERS'
# "remind me to take", and _cmd_reminder dispatches well before
# _cmd_med_add -- so "remind me to take my blood pressure pill at 8am",
# the most natural way to ask, became a generic reminder and the
# medication was never actually tracked. The reminder still fired, which
# is why this could sit unnoticed: the visible half worked and only the
# adherence record silently didn't happen.
_REMINDER_SHADOWED_TRIGGERS = [
    t for t in MED_ADD_TRIGGERS
    if any(r in t for r in REMINDER_TRIGGERS)
]

# Trigger lists that name a real feature, mapped to how FRIDAY should
# describe it. Only lists whose phrases are specific enough that matching
# one is genuinely a request for that feature -- deliberately excludes
# vague ones (CANCEL_TRIGGERS, SEND_TRIGGERS, CALL_TRIGGERS' bare
# "call ") that turn up inside ordinary conversation, since claiming a
# feature is unavailable when the boss was just talking is its own kind
# of wrong answer.
_FEATURE_TRIGGERS = {
    "EMAIL_TRIGGERS": "reading your inbox",
    "TRIAGE_TRIGGERS": "inbox triage",
    "DRAFT_TRIGGERS": "drafting an email reply",
    "COMPOSE_SEND_TRIGGERS": "sending email",
    "CALENDAR_ADD_TRIGGERS": "adding a calendar event",
    "MED_ADD_TRIGGERS": "medication tracking",
    "MED_TAKEN_TRIGGERS": "medication tracking",
    "MED_SKIP_TRIGGERS": "medication tracking",
    "MED_SCHEDULE_TRIGGERS": "your medication schedule",
    "TASK_ADD_TRIGGERS": "your task list",
    "TASK_SHOW_TRIGGERS": "your task list",
    "NOTE_TRIGGERS": "notes",
    "GOAL_REPORT_TRIGGERS": "goals",
    "GOAL_ADD_TRIGGERS": "goals",
    "GOAL_PROGRESS_TRIGGERS": "goals",
    "HABIT_LOG_TRIGGERS": "habit tracking",
    "JOURNAL_TRIGGERS": "your journal",
    "REMINDER_TRIGGERS": "reminders",
    "SPOTIFY_PLAY_TRIGGERS": "Spotify",
    "SPOTIFY_STOP_TRIGGERS": "Spotify",
    "TRAVEL_TRIGGERS": "travel intel",
    "FOCUS_TRIGGERS": "focus mode",
    "CATCHUP_TRIGGERS": "catching you up",
    "SMS_TRIGGERS": "sending a text",
}


def _matched_but_unavailable(p_lower: str) -> str | None:
    """Name the feature a request was clearly asking for when no handler
    claimed it -- see the call site for why silence here is dangerous.

    Returns the longest-matching feature so a specific phrase wins over a
    vague one ("put on my calendar" naming the calendar rather than
    Spotify's "put on")."""
    best, best_len = None, 0
    for list_name, feature in _FEATURE_TRIGGERS.items():
        phrases = globals().get(list_name)
        if not isinstance(phrases, list):
            continue
        for phrase in phrases:
            if phrase in p_lower and len(phrase) > best_len:
                best, best_len = feature, len(phrase)
    return best


MED_TAKEN_TRIGGERS = [
    "i took my", "took my medicine", "just took my",
]
MED_SKIP_TRIGGERS = [
    "skip my", "skipping my", "not taking my",
]
MED_SCHEDULE_TRIGGERS = [
    "my medicine schedule", "what medicine", "medicine schedule",
    "what do i need to take", "medication schedule",
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


HOMEKIT_TRIGGERS = {
    "turn off lights": "shortcuts run 'Lights Off'",
    "turn on lights": "shortcuts run 'Lights On'",
    "i'm leaving": "shortcuts run 'Leaving Home'",
    "i'm home": "shortcuts run 'Arriving Home'",
    "lock the door": "shortcuts run 'Lock Door'",
    "night mode": "shortcuts run 'Night Mode'",
}

HA_STATUS_TRIGGERS = [
    "what's on my home assistant", "whats on my home assistant",
    "what's on home assistant", "home assistant status",
    "list my devices", "list my home assistant devices",
]

# Checked only after HOMEKIT_TRIGGERS, so phrases like "turn on lights"
# keep going through the existing Mac Bridge/Shortcuts path above and
# never reach here — this dict is for devices HA controls directly.
HA_DEVICE_TRIGGERS = {
    "samsung tv": "media_player.livingrm_un50nu6950",
    "living room tv": "media_player.livingrm_un50nu6950",
    "tv": "media_player.livingrm_un50nu6950",
}


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

# ── Health & status ───────────────────────────────────────────────────────────
# /health itself is registered at the very top of this file, before any of
# the imports below it that could fail.

@app.route("/")
def home():
    return jsonify({
        "status": f"{FRIDAY_NAME} V{FRIDAY_VERSION} ONLINE", "core": CORE_STATUS,
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
        # Real telemetry for the HUD overlay's edge readouts — replaces
        # placeholder ALT/HDG/LAT values that never reflected anything.
        "locked": suit_lockdown.is_locked() if LOCKDOWN_OK else False,
        "hulkbuster": hulkbuster.status() if HULKBUSTER_OK else {"deployed": False},
    })


# Backward-compatible alias — the previous server.py exposed a /status route.
@app.route("/status")
def status_alias():
    return state()


# ── Main command endpoint ─────────────────────────────────────────────────────

# ── NLU dispatcher: one function per trigger-check block, called in
# the exact original order from command() below. Each returns the
# jsonify(...) response (or (response, status) tuple) if its trigger
# matched, else None to fall through to the next check. Extracted
# mechanically from the original inline if-chain -- same behavior,
# same ordering, just named and callable individually.
def _cmd_lockdown_locked(prompt):
    if LOCKDOWN_OK and suit_lockdown.is_locked():
        if suit_lockdown.try_unlock(prompt):
            response = "Unlocked. Welcome back, boss."
            _log(prompt, response, "lockdown_unlock")
            return jsonify({"response": response, "mode": "lockdown_unlock"})
        response = "System locked. Provide the passphrase to unlock."
        _log(prompt, response, "lockdown")
        return jsonify({"response": response, "mode": "lockdown", "blocked": True})


def _cmd_lockdown_trigger(prompt):
    if LOCKDOWN_OK and any(t in prompt.lower() for t in LOCKDOWN_TRIGGERS):
        suit_lockdown.activate(reason="voice command")
        response = "Lockdown active. Standing by."
        _log(prompt, response, "lockdown_activate")
        return jsonify({"response": response, "mode": "lockdown_activate"})


# Safety commands that only *nearly* match. Confirmed live: "lockdown"
# on its own matches none of LOCKDOWN_TRIGGERS ("lockdown now",
# "emergency lockdown", ...), so it fell through the whole chain to the
# conversational model, which answered "Boss, lockdown initiated." --
# with its badge on it, and nothing locked.
#
# That is the most dangerous shape of the improvisation problem this
# branch has been chasing. A fabricated "diagnostics ran" wastes time; a
# fabricated "you are locked down" means believing the system is secured
# during exactly the situation where it isn't.
#
# Deliberately does NOT activate on a near miss. Lockdown is one-way
# without ENDGAME_PASSPHRASE or a redeploy with RESET_LOCKDOWN, and
# "lockdown" turns up in ordinary talk about lockdown. Guessing wrong in
# the activating direction is worse than asking for the exact words. So
# this fails closed and loudly: nothing happens, and it says so.
_SAFETY_NEAR_MISS = {
    "lockdown": (
        "lockdown", "lock down", "lock it down", "lock the suit",
        "secure the system", "seal it up",
    ),
    "mayday": ("mayday", "distress call", "emergency broadcast"),
}


def _cmd_safety_near_miss(prompt, p_lower):
    """Runs after the real safety handlers, so an exact trigger has
    already been claimed and returned before this sees anything."""
    for kind, phrases in _SAFETY_NEAR_MISS.items():
        if not any(ph in p_lower for ph in phrases):
            continue
        if kind == "lockdown":
            response = ("I have not locked anything down, boss — that wasn't the "
                        "phrase. Say \"lockdown now\" and I'll do it.")
        else:
            response = (f"I have not sent a mayday, boss — that wasn't the phrase. "
                        f"Say \"{MAYDAY_PHRASE}\" and I will.")
        logging.warning(f"[safety] near-miss on {kind}: {prompt[:120]!r} — took no action")
        _log(prompt, response, "safety_near_miss")
        return jsonify({"response": response, "mode": "safety_near_miss",
                         "acted": False, "kind": kind})


def _cmd_mayday(prompt):
    if MAYDAY_PHRASE in prompt.lower():
        response = "Mayday received. What's happening, boss?"
        _log(prompt, response, "MAYDAY")
        try:
            # CRITICAL -> Pushover priority 2 (emergency) -> notify()'s
            # _pushover() path -> friday_caps._pushover_alert(), which
            # applies retry/expire itself for priority 2 — a distress
            # signal that only pushes once, with no retry-until-acked,
            # defeats its own purpose if boss's phone is silenced or
            # out of reach. Same tier as friday_health.py's
            # critical-vitals alert.
            from services.notifications import critical
            critical(
                "FRIDAY MAYDAY",
                f"Mayday phrase triggered. Emergency contact on file: {EMERGENCY_CONTACT_PHONE}",
            )
        except Exception as e:
            logging.warning(f"MAYDAY notify failed: {e}")
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


def _cmd_safe_checkin(prompt):
    if any(t in prompt.lower() for t in SAFE_TRIGGERS):
        response = "Good to hear, boss. Standing down." if CHECKIN_OK else "Glad to hear it, boss."
        if CHECKIN_OK:
            checkin_system.confirm_safe()
        _log(prompt, response, "safe_checkin")
        return jsonify({"response": response, "mode": "safe_checkin"})


def _cmd_security_screen(prompt):
    if SECURITY_OK:
        screen = friday_security.screen_request(friday_security.client_ip(request), prompt)
        if screen.get("blocked"):
            return jsonify({"response": "Request blocked.", "blocked": True}), 403


def _cmd_learn_voice_mode(prompt):
    try:
        if voice_memory:
            voice_memory.analyze_and_learn(prompt)
            best_mode = voice_memory.get_current_best_mode()
            if friday_brain and not COVERAGE_MODE:
                friday_brain.set_voice_mode(best_mode)
    except Exception:
        pass


def _cmd_dark_mode(prompt):
    if PROTOCOLS_OK and friday_protocols.range_level == RangeLevel.DARK:
        response = friday_protocols.emergency_response(prompt)
        _log(prompt, response, "emergency")
        return jsonify({"response": response, "mode": "emergency", "range": "dark"})


def _cmd_capabilities(prompt):
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


def _cmd_weather(prompt, p_lower):
    if "weather" in p_lower:
        location = ""
        for marker in ("weather in ", "weather for ", "weather at "):
            if marker in p_lower:
                location = p_lower.split(marker, 1)[1].strip().rstrip("?.!")
                break
        brief = get_weather_brief(location)
        response = brief if brief else "Couldn't reach a weather service right now, boss."
        _log(prompt, response, "weather")
        return jsonify({"response": response, "mode": "weather"})


def _cmd_news(prompt, p_lower):
    if ("news" in p_lower or "what's happening" in p_lower) and news_anchor:
        response = news_anchor.morning_brief()
        _log(prompt, response, "news")
        return jsonify({"response": response, "mode": "news"})


def _cmd_translate(prompt, p_lower):
    if "translate" in p_lower and translator:
        text = p_lower.replace("translate", "").replace("friday", "").strip()
        result = translator.translate(text)
        _log(prompt, result["translation"], "translate")
        return jsonify({"response": result["translation"], "mode": "translate"})


def _cmd_code_review(prompt, p_lower):
    if ("review this code" in p_lower or "fix this code" in p_lower) and friday_code:
        result = friday_code.quick_review(prompt)
        _log(prompt, result["review"], "code")
        return jsonify({"response": result["review"], "mode": "code"})


def _cmd_remember_this(prompt, p_lower):
    if ("remember this" in p_lower or "store this" in p_lower) and second_brain:
        result = second_brain.ingest(prompt)
        response = f"Stored: {result['summary']}" if result["summary"] else "Stored, boss."
        _log(prompt, response, "brain")
        return jsonify({"response": response, "mode": "brain"})


def _cmd_people_brief(prompt, p_lower):
    if "people brief on " in p_lower and relationships:
        name = p_lower.split("people brief on ")[-1].strip()
        result = relationships.get_intel(name)
        response = result.get("brief") or f"No intel on {name} yet, boss."
        _log(prompt, response, "intel")
        return jsonify({"response": response, "mode": "intel"})


def _cmd_caller_id(prompt, p_lower):
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


def _cmd_call_initiate(prompt, p_lower):
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


def _cmd_sms_send(prompt, p_lower):
    if any(t in p_lower for t in SMS_TRIGGERS) and friday_brain:
        from services.friday_phone import friday_phone
        import re as rex
        extract = friday_brain.think(
            f"From this: '{prompt}'\n"
            f"Extract who to text and what to say. If it's addressed "
            f"to the boss themself ('text me'), use \"me\" for 'to'.\n"
            f'JSON: {{"to": str, "message": str}}',
            raw=True,
        )
        try:
            clean = rex.sub(r"```json|```", "", extract["response"]).strip()
            data = json.loads(clean)
            to = data.get("to", "")
            message = data.get("message", "")
        except Exception:
            to, message = "", ""

        if to.strip().lower() == "me":
            number = os.environ.get("MY_PHONE_NUMBER", "")
        else:
            contact = friday_contacts.find_by_name(to) if friday_contacts else {}
            number = contact.get("phone", "")

        if not number or not message:
            response = (
                "I don't have a number for that, boss — add one with "
                "'add contact' first, or tell me what to say."
                if not number else "What should it say, boss?"
            )
            _log(prompt, response, "sms_send")
            return jsonify({"response": response, "mode": "sms_send"})

        result = friday_phone.send_sms(number, message)
        if result.get("ok"):
            response = "Sent, boss."
        else:
            response = f"Couldn't send that, boss — {result.get('error', 'unknown error')}."
        _log(prompt, response, "sms_send")
        return jsonify({"response": response, "mode": "sms_send", **result})


def _cmd_catchup(prompt, p_lower):
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


def _cmd_focus(prompt, p_lower):
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


def _cmd_habit_log(prompt, p_lower):
    if any(t in p_lower for t in HABIT_LOG_TRIGGERS) and habits and friday_brain:
        result = friday_brain.think(f"Extract habit from: {prompt}\nOne word reply.")
        habit_name = result["response"].strip()
        if habit_name:
            log_result = habits.log(habit_name)
            streak = log_result.get("streak", 1)
            response = f"Logged {habit_name}, boss. That's a {streak}-day streak."
            _log(prompt, response, "habit")
            return jsonify({"response": response, "mode": "habit"})


def _cmd_journal(prompt, p_lower):
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


def _cmd_probability(prompt, p_lower):
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


def _cmd_recon(prompt, p_lower):
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


def _cmd_diagnostics(prompt, p_lower):
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


def _cmd_self_repair(prompt, p_lower):
    CONFIRM_TRIGGERS = [
        "confirm the repair", "confirm repair", "apply the repair",
        "apply the fix", "go ahead and repair yourself",
    ]
    RUN_TRIGGERS = [
        "self repair", "repair yourself", "diagnose yourself",
        "fix yourself", "check yourself for bugs",
    ]

    # Confirmed live: "run a self repair" came back "Self repair
    # initiated, boss. Calendar still not connected." -- an answer
    # invented wholesale by the conversational model, with its badge on
    # it, in 321ms (a real run shells out to pytest and takes seconds).
    #
    # The mechanism: SELF_REPAIR_OK was False on that deploy, so both
    # branches below were skipped, this returned None, and the request
    # fell through the rest of the chain to the plain model -- which has
    # no idea whether self-repair exists and improvised something
    # confident and wrong.
    #
    # Answering honestly here is the whole point. "I can't run that right
    # now" is a useful answer; a fabricated "initiated" is worse than
    # silence, because the boss believes a diagnostic ran when nothing
    # did. Same failure as FRIDAY denying she could read Gmail, in the
    # opposite direction.
    if not SELF_REPAIR_OK and any(t in p_lower for t in CONFIRM_TRIGGERS + RUN_TRIGGERS):
        response = ("Self-repair isn't loaded on this deploy, boss — I can't "
                    "diagnose myself right now. Nothing else is necessarily wrong.")
        logging.warning("[self_repair] asked to run but SELF_REPAIR_OK is False")
        _log(prompt, response, "self_repair")
        return jsonify({"response": response, "mode": "self_repair",
                         "status": "unavailable"})

    if any(t in p_lower for t in CONFIRM_TRIGGERS) and SELF_REPAIR_OK:
        result = self_repair.confirm_repair()
        response = (f"Done, boss — {result['target']} is patched and live."
                    if result["applied"] else f"Couldn't apply it: {result['reason']}")
        _log(prompt, response, "self_repair")
        audio_file = friday_speak(response) if VOICE_OK else None
        return jsonify({"response": response, "mode": "self_repair",
                         "has_audio": bool(audio_file), "audio_file": audio_file, **result})

    if any(t in p_lower for t in RUN_TRIGGERS) and SELF_REPAIR_OK:
        # A repair run takes as long as the test suite, and gunicorn kills
        # any worker still busy after its timeout -- confirmed live, every
        # attempt died as "[CRITICAL] WORKER TIMEOUT ... Error handling
        # request POST /command" with the worker killed mid-run, which is
        # why the HUD kept dropping to offline mode instead of getting an
        # answer. So this starts the run and returns; the result is
        # collected by asking again.
        state = self_repair.run_state()

        if state["running"]:
            response = ("Still running diagnostics, boss — ask me again in a "
                        "minute and I'll have the answer.")
            _log(prompt, response, "self_repair")
            return jsonify({"response": response, "mode": "self_repair",
                             "status": "running"})

        # A finished run that hasn't been reported yet is the answer to
        # this question -- reporting it here is what makes "ask again"
        # work as the way to collect it.
        result = state.get("result")
        if result is None:
            started = self_repair.start_background_repair()
            response = ("Running full diagnostics now, boss — that's the whole "
                        "test suite, so give me a minute, then ask again.")
            _log(prompt, response, "self_repair")
            return jsonify({"response": response, "mode": "self_repair",
                             "status": "started", **started})

        status = result["status"]
        RESPONSES = {
            "nothing_to_repair": "Ran full diagnostics — every test passes, nothing to repair, boss.",
            # Distinct from cannot_localize on purpose: "I couldn't run
            # my tests" and "a test failed in a place I don't watch" are
            # completely different problems, and reporting the second
            # when it's really the first sends the boss hunting a bug
            # that doesn't exist.
            "cannot_run_tests": "Couldn't run my own test suite here, boss — pytest isn't "
                                 "installed in this deploy, so I can't diagnose myself. "
                                 "Nothing's necessarily wrong.",
            "cannot_localize": "Found a failing test but couldn't trace it back to one of my "
                                "watched files — needs a human look.",
            "propose_failed": f"Found the failure in {result.get('target')} but couldn't "
                               f"generate a fix: {result.get('reason')}",
            "cannot_apply_safely": f"Found a fix for {result.get('target')} but couldn't apply "
                                    f"it safely: {result.get('reason')}",
            "sandbox_fix_invalid": f"Tried a fix for {result.get('target')} — it doesn't even "
                                    f"compile, discarding it.",
            "sandbox_fix_failed": f"Tried a fix for {result.get('target')} in a sandbox — "
                                   f"still fails, discarding it.",
            "awaiting_confirmation": f"Found and sandbox-tested a fix for {result.get('target')}, "
                                      f"boss. Full suite passes in the sandbox. Say \"apply the "
                                      f"fix\" and I'll make it live.",
        }
        response = RESPONSES.get(status, f"Self-repair status: {status}")
        # Reported -- drop it so the next ask runs fresh diagnostics
        # rather than replaying this answer. The one exception is a fix
        # waiting on "apply the fix": clearing that would strand the
        # staged patch with no way to refer to it.
        if status != "awaiting_confirmation":
            self_repair.clear_run_state()
        _log(prompt, response, "self_repair")
        audio_file = friday_speak(response) if VOICE_OK else None
        return jsonify({"response": response, "mode": "self_repair",
                         "has_audio": bool(audio_file), "audio_file": audio_file, "status": status})


def _cmd_cross_check(prompt, p_lower):
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


def _cmd_combat_mode(prompt, p_lower):
    if any(t in p_lower for t in COMBAT_TRIGGERS) and friday_brain:
        friday_brain.set_voice_mode("combat")
        response = "Combat mode. Standing by."
        _log(prompt, response, "mode")
        return jsonify({"response": response, "mode": "combat"})


def _cmd_normal_mode(prompt, p_lower):
    if any(t in p_lower for t in NORMAL_MODE_TRIGGERS) and friday_brain:
        friday_brain.set_voice_mode("normal")
        response = "Standing down, boss."
        _log(prompt, response, "mode")
        return jsonify({"response": response, "mode": "normal"})


def _cmd_priority(prompt, p_lower):
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


def _cmd_travel(prompt, p_lower):
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


def _cmd_spotify_stop(prompt, p_lower):
    if any(t in p_lower for t in SPOTIFY_STOP_TRIGGERS) and friday_spotify:
        friday_spotify.pause()
        response = "Pausing, boss."
        _log(prompt, response, "spotify")
        return jsonify({"response": response, "mode": "spotify"})


def _cmd_spotify_play(prompt, p_lower):
    # Defer to a more specific command that merely happens to contain a
    # music trigger as a substring -- see _SPOTIFY_SHADOWED_TRIGGERS.
    if any(t in p_lower for t in _SPOTIFY_SHADOWED_TRIGGERS):
        return None

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


def _json_from_model(text: str):
    """Parse a JSON object out of an LLM reply.

    The bare `re.sub("```json|```")` + json.loads pattern used in a
    dozen places here needs the reply to be *exactly* JSON and nothing
    else -- one "Here's the event:" preamble or a trailing sentence and
    it raises, which upstream turns into a generic "wasn't sure"
    message. Falling back to the outermost {...} span makes the common
    chatty-model case work instead of failing indistinguishably from a
    genuine "no date given".

    Raises (rather than returning None) on genuinely unparseable input,
    so callers can tell "the model said something unusable" apart from
    "the model correctly reported nothing to extract"."""
    clean = re.sub(r"```json|```", "", text or "").strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        start, end = clean.find("{"), clean.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(clean[start:end + 1])


def _cmd_calendar_add(prompt, p_lower):
    global _pending_calendar_add

    if _pending_calendar_add and time.time() > _pending_calendar_add.get("expires", 0):
        _pending_calendar_add = {}

    is_new_request = any(t in p_lower for t in CALENDAR_ADD_TRIGGERS)
    is_pending_reply = bool(_pending_calendar_add) and not is_new_request

    if is_pending_reply and any(t in p_lower for t in CANCEL_TRIGGERS):
        _pending_calendar_add = {}
        response = "Scrapped it, boss."
        _log(prompt, response, "calendar")
        return jsonify({"response": response, "mode": "calendar"})

    if not (is_new_request or is_pending_reply) or not friday_brain:
        return

    if not (friday_calendar and friday_calendar.is_connected()):
        _pending_calendar_add = {}
        response = "Your calendar isn't connected yet, boss."
        _log(prompt, response, "calendar")
        return jsonify({"response": response, "mode": "calendar"})

    # Same reasoning as _cmd_email_compose_send: a pending reply only
    # makes sense folded in with the original ask -- "3pm tomorrow"
    # is nothing on its own without "schedule a meeting with Jane".
    context = prompt
    if is_pending_reply:
        context = f"{_pending_calendar_add.get('context', '')}\nBoss's follow-up reply: {prompt}"

    # "September 1st Highschool Starts" is a perfectly ordinary calendar
    # entry with a date and no clock time -- an all-day event. The older
    # prompt asked for datetimes only and told the model to return empty
    # strings when no *time* was given, so requests like that came back
    # "wasn't sure what to schedule there, boss -- try again with a
    # time?" (confirmed live), pushing the boss to invent a time for
    # something that doesn't have one. Date-only values are now a
    # first-class answer; friday_calendar.create_event() reads the shape
    # of the value to pick Google's all-day vs. timed event fields.
    result = friday_brain.think(
        f"Extract a calendar event from: {context}\n"
        f"Current time: {datetime.datetime.now().isoformat()}\n\n"
        f'Reply as JSON: {{"title": str, "start": str, "end": str}}\n\n'
        f"If the event has a specific time of day, use full ISO 8601 "
        f'datetimes ("2026-09-01T15:00:00"); when no duration is given, '
        f"default to 30 minutes.\n"
        f"If it's an all-day event -- a date with no time of day -- use "
        f'plain dates ("2026-09-01") for both start and end, where end is '
        f"the last day the event covers (the same date for a single-day "
        f"event).\n"
        f"Only if the text specifies no date at all, return empty strings "
        f"for start/end rather than guessing. JSON only.",
        # Without raw=True this never reached the model at all: the
        # prompt quotes the boss's own words, so "put on my calendar ..."
        # tripped friday_brain's "my calendar" instant-response guard and
        # came back "Your calendar isn't connected yet, boss." -- which
        # then failed to parse as JSON. Confirmed live.
        raw=True,
    )
    # Previously one bare `except Exception` around parse + create, so a
    # malformed model reply, a genuine "no date in the request", and
    # Google rejecting the event all produced the identical "wasn't sure
    # what to schedule" answer -- and nothing was logged, so the actual
    # cause wasn't recoverable afterwards either. Same failure shape that
    # made the SMTP outage take four passes to diagnose. Split up so each
    # cause says what it is and leaves a log line behind.
    try:
        data = _json_from_model(result["response"])
    except Exception as e:
        logging.warning(
            f"[calendar] couldn't parse event JSON ({e}); "
            f"model said: {result.get('response', '')[:300]!r}"
        )
        data = None

    if data is None:
        _pending_calendar_add = {} if is_pending_reply else {
            "context": context, "expires": time.time() + CALENDAR_ADD_PENDING_WINDOW
        }
        response = "Couldn't read that one back, boss — say it again?"
    elif not data.get("start") or not data.get("end"):
        # The model followed instructions and reported no date present.
        if is_pending_reply:
            # One miss already used -- give up rather than re-arming
            # pending state and risking a later unrelated message
            # getting folded into this same attempt.
            _pending_calendar_add = {}
            response = "Still wasn't sure what to schedule, boss — try the full request again?"
        else:
            _pending_calendar_add = {"context": context, "expires": time.time() + CALENDAR_ADD_PENDING_WINDOW}
            # "with a time" was actively misleading once all-day events
            # became valid -- a date is now enough on its own.
            response = "Wasn't sure what to schedule there, boss — try again with a date?"
    else:
        title = data.get("title") or "Event"
        try:
            created = friday_calendar.create_event(title, data["start"], data["end"])
        except Exception as e:
            logging.warning(f"[calendar] create_event raised: {e!r}")
            created = {"error": "Couldn't add that to your calendar, boss."}

        if created.get("ok"):
            response = f'Added "{title}" to your calendar, boss.'
        else:
            # A Google-side rejection is its own thing, not "I didn't
            # understand you" -- saying the latter would send the boss
            # off rewording a request that parsed perfectly well.
            logging.warning(
                f"[calendar] create_event failed for {title!r} "
                f"({data['start']} -> {data['end']}): {created.get('error')}"
            )
            response = created.get("error", "Couldn't add that to your calendar, boss.")
        _pending_calendar_add = {}

    _log(prompt, response, "calendar")
    return jsonify({"response": response, "mode": "calendar"})


def _cmd_goal_report(prompt, p_lower):
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


def _cmd_goal_add(prompt, p_lower):
    if any(t in p_lower for t in GOAL_ADD_TRIGGERS) and goals and friday_brain:
        import re as rex
        extract = friday_brain.think(
            f"Extract goal from: '{prompt}'\n"
            f'Reply as JSON: {{"name": str, "description": str}}',
            raw=True,
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


def _cmd_goal_progress(prompt, p_lower):
    if any(t in p_lower for t in GOAL_PROGRESS_TRIGGERS) and goals:
        log_result = goals.log_progress(work_done=prompt, auto_detect=True)
        if log_result.get("logged"):
            response = f"Logged progress on {log_result['goal']}, boss. Session {log_result['sessions']}."
        else:
            response = "Noted — didn't match it to a tracked goal, boss."
        _log(prompt, response, "goal_progress")
        return jsonify({"response": response, "mode": "goal_progress"})


def _cmd_email_draft(prompt, p_lower):
    if any(t in p_lower for t in DRAFT_TRIGGERS) and friday_gmail and friday_brain:
        import re as rex
        extract = friday_brain.think(
            f"From this: '{prompt}'\n"
            f"Extract: who to reply to and what to say.\n"
            f'JSON: {{"to": str, "instruction": str}}',
            raw=True,
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
                message_id=found.get("message_id", ""),
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


def _cmd_email_send(prompt, p_lower):
    if any(t in p_lower for t in SEND_TRIGGERS) and friday_gmail:
        result = friday_gmail.send_draft()
        if result.get("ok"):
            response = f"Sent, boss. On its way to {result.get('to', '')}."
        else:
            response = f"Couldn't send that, boss — {result.get('error', 'unknown error')}."
        _log(prompt, response, "email_send")
        return jsonify({"response": response, "mode": "email_send", **result})


def _cmd_email_compose_send(prompt, p_lower):
    global _pending_compose_send

    if _pending_compose_send and time.time() > _pending_compose_send.get("expires", 0):
        _pending_compose_send = {}

    is_new_request = any(t in p_lower for t in COMPOSE_SEND_TRIGGERS)
    is_pending_reply = bool(_pending_compose_send) and not is_new_request

    if is_pending_reply and any(t in p_lower for t in CANCEL_TRIGGERS):
        _pending_compose_send = {}
        response = "Scrapped it, boss."
        _log(prompt, response, "email_compose_send")
        return jsonify({"response": response, "mode": "email_compose_send"})

    if not (is_new_request or is_pending_reply) or not friday_gmail or not friday_brain:
        return

    import re as rex
    # A pending reply gets folded in with the original ask, not extracted
    # alone -- "jane@x.com, running late" only makes sense as a recipient
    # + body next to "send an email to my boss", not by itself.
    context = prompt
    if is_pending_reply:
        context = f"{_pending_compose_send.get('context', '')}\nBoss's follow-up reply: {prompt}"

    extract = friday_brain.think(
        f"From this: '{context}'\n"
        f"Extract who to email and what to say.\n"
        f'JSON: {{"to": str, "subject": str, "body": str, "attachment": str|null}}\n'
        f"'to' should be the raw email address if one appears in the "
        f"text, otherwise the name/description as given. 'subject' "
        f"should be short and inferred from the message if none is "
        f"stated. 'body' should be the message to send, written out "
        f"in full sentences. 'attachment' is the name of a file to "
        f"attach if the boss names one (e.g. 'email them the "
        f"shopping-list file'), otherwise null. If the text doesn't "
        f"actually specify a recipient or message content, return "
        f"empty strings rather than guessing.",
        raw=True,
    )
    try:
        clean = rex.sub(r"```json|```", "", extract["response"]).strip()
        data = json.loads(clean)
        to = data.get("to", "")
        subject = data.get("subject", "")
        body = data.get("body", "")
        attachment = data.get("attachment") or None
    except Exception:
        to, subject, body, attachment = "", "", "", None

    if not friday_gmail.extract_address(to):
        # No bare address in the prompt or the extraction — try
        # the contact book first (a name FRIDAY actually has an
        # address for), then fall back to matching it against a
        # recent inbox sender by name, the same lookup the
        # reply-draft flow uses.
        contact = friday_contacts.find_by_name(to) if friday_contacts else {}
        if contact.get("email"):
            to = contact["email"]
        else:
            found = friday_gmail.find_email(to)
            if found:
                to = found.get("from", "")

    if not to or not body:
        if is_pending_reply:
            # Already gave the boss one chance to answer -- re-asking the
            # identical question and re-arming pending state again risks
            # silently capturing whatever they say *next* too, including
            # something completely unrelated they've moved on to. One
            # miss ends the attempt instead of looping.
            _pending_compose_send = {}
            response = "Still couldn't tell who or what to send, boss — try the full request again?"
        else:
            _pending_compose_send = {"context": context, "expires": time.time() + COMPOSE_SEND_PENDING_WINDOW}
            response = "Who's it going to, and what should it say, boss?"
        _log(prompt, response, "email_compose_send")
        return jsonify({"response": response, "mode": "email_compose_send"})

    _pending_compose_send = {}
    result = friday_gmail.send_email(
        to=to, subject=subject, body=body,
        attachments=[attachment] if attachment else None,
    )
    if result.get("ok"):
        response = f"Sent, boss. On its way to {result.get('to', '')}."
    else:
        response = f"Couldn't send that, boss — {result.get('error', 'unknown error')}."
    _log(prompt, response, "email_compose_send")
    return jsonify({"response": response, "mode": "email_compose_send", **result})


def _cmd_email_triage(prompt, p_lower):
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


def _cmd_email_summary(prompt, p_lower):
    if any(t in p_lower for t in EMAIL_TRIGGERS) and friday_gmail:
        summary = friday_gmail.summarize_inbox()
        _log(prompt, summary, "email")
        return jsonify({"response": summary, "mode": "email"})


def _cmd_note(prompt, p_lower):
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


def _extract_file_name(prompt: str, p_lower: str) -> str:
    for marker in (" called ", " named ", " titled "):
        if marker in p_lower:
            tail = prompt[p_lower.index(marker) + len(marker):]
            name = tail.split(":", 1)[0].strip().rstrip(".,!?")
            if name:
                return name
    return ""


def _safe_filename(name: str) -> str:
    """A name spoken in a chat prompt ends up in a filesystem Path join
    later (services/friday_gmail.py materializes it as an email
    attachment) -- strip path separators and ".." before that ever
    happens, rather than trusting free text as a path component."""
    import re as rex
    name = name.strip().replace("/", "-").replace("\\", "-")
    name = rex.sub(r"\.\.+", ".", name)
    name = rex.sub(r"[^A-Za-z0-9 ._-]", "", name)
    return name.strip(" .-")


def _cmd_create_file(prompt, p_lower):
    if any(t in p_lower for t in FILE_TRIGGERS):
        import re as rex
        from core.friday_memory import save_generated_file

        name = _extract_file_name(prompt, p_lower)
        # An explicit ":" is the strongest signal of "here's the actual
        # content" -- anything short of that gets drafted, same as a
        # "draft an email" request with no body dictated.
        content = prompt.split(":", 1)[1].strip() if ":" in prompt else ""

        if not content and friday_brain:
            drafted = friday_brain.think(
                f"The boss asked: \"{prompt}\"\n"
                f"Write only the content that file should contain -- no "
                f"preamble, no explanation, just the text of the file itself."
            )["response"]
            content = drafted.strip()

        if not name:
            seed = content or prompt
            words = rex.sub(r"[^a-z0-9\s]", "", seed.lower()).split()[:5]
            name = "-".join(words) or "note"
        name = _safe_filename(name) or "note"
        if "." not in name:
            name = f"{name}.txt"

        entry = {
            "name": name, "content": content,
            "created_at": datetime.datetime.now().isoformat(), "context": prompt,
        }
        save_generated_file(entry)

        response = f"Made it, boss — \"{name}\", ready to download or send."
        _log(prompt, response, "create_file")
        return jsonify({
            "response": response, "mode": "create_file",
            "file": {"name": name, "content": content},
        })


def _clarify(prompt, question, options, mode_tag):
    """A structured question with a small, enumerable set of answers --
    the HUD renders `options` as real clickable chips (see hud.js's
    addMsg()) instead of leaving the boss to type a free-text reply to
    a question that only ever has a few valid answers. `options` is a
    list of {"label": display text, "value": what gets sent back} --
    clicking one round-trips through the normal /command endpoint with
    that exact value as the next prompt, same as typing it would."""
    _log(prompt, question, mode_tag)
    return jsonify({
        "response": question, "mode": mode_tag,
        "clarify": {"question": question, "options": options},
    })


def _cmd_file_recall(prompt, p_lower):
    if any(t in p_lower for t in FILE_RECALL_TRIGGERS):
        from core.friday_memory import get_generated_file, get_generated_files

        name = _extract_file_name(prompt, p_lower)
        entry = get_generated_file(name) if name else None
        if not entry:
            if name:
                response = f"Couldn't find a file called \"{name}\", boss."
                _log(prompt, response, "file_recall")
                return jsonify({"response": response, "mode": "file_recall"})

            recent = get_generated_files(5)
            if not recent:
                response = "Which file, boss? Give me the name."
                _log(prompt, response, "file_recall")
                return jsonify({"response": response, "mode": "file_recall"})

            options = [{"label": f["name"], "value": f["name"]} for f in reversed(recent)]
            return _clarify(prompt, "Which file, boss?", options, "file_recall")

        response = f"Here's \"{entry['name']}\", boss."
        _log(prompt, response, "file_recall")
        return jsonify({
            "response": response, "mode": "file_recall",
            "file": {"name": entry["name"], "content": entry.get("content", "")},
        })


def _cmd_reminder(prompt, p_lower):
    # Defer to medication tracking when the ask is specifically about
    # taking a medicine -- see _REMINDER_SHADOWED_TRIGGERS.
    if any(t in p_lower for t in _REMINDER_SHADOWED_TRIGGERS):
        return None

    if any(t in p_lower for t in REMINDER_TRIGGERS) and friday_brain:
        import re as rex
        result = friday_brain.think(
            f"Extract reminder from: {prompt}\n\n"
            f"Reply as JSON: {{\"task\": str, \"minutes\": int}}\n"
            f"Examples:\n"
            f"'remind me in 30 minutes to call back' -> {{\"task\":\"call back\",\"minutes\":30}}\n"
            f"'remind me at 3pm' -> {{\"task\":\"reminder\",\"minutes\": calculated from now}}\n"
            f"JSON only.",
            # raw=True: this parses the reply as JSON, so it must skip
            # think()'s speech pipeline -- see core/friday_brain.py.
            raw=True,
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


def _cmd_task_show(prompt, p_lower):
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


def _cmd_task_add(prompt, p_lower):
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


def _cmd_med_schedule(prompt, p_lower):
    if any(t in p_lower for t in MED_SCHEDULE_TRIGGERS) and medicine_tracker:
        response = medicine_tracker.get_schedule_summary()
        _log(prompt, response, "medicine")
        return jsonify({"response": response, "mode": "medicine"})


def _cmd_med_taken(prompt, p_lower):
    if any(t in p_lower for t in MED_TAKEN_TRIGGERS) and medicine_tracker and friday_brain:
        extract = friday_brain.think(
            f"Extract medicine name from: '{prompt}'\n"
            f"Reply with just the name, nothing else."
        )
        med_name = extract["response"].strip()
        if med_name:
            result = medicine_tracker.log_taken(med_name)
            response = (
                f"Logged, boss. {med_name} marked as taken."
                if result.get("logged")
                else f"Couldn't find {med_name} in your schedule, boss."
            )
        else:
            response = "Which medicine did you take, boss?"
        _log(prompt, response, "medicine")
        return jsonify({"response": response, "mode": "medicine"})


def _cmd_med_skip(prompt, p_lower):
    if any(t in p_lower for t in MED_SKIP_TRIGGERS) and medicine_tracker and friday_brain:
        extract = friday_brain.think(
            f"Extract medicine name from: '{prompt}'\n"
            f"Reply with just the name, nothing else."
        )
        med_name = extract["response"].strip()
        if med_name:
            result = medicine_tracker.log_skipped(med_name)
            response = (
                f"Got it, boss. {med_name} logged as skipped."
                if result.get("logged")
                else f"Couldn't find {med_name} in your schedule, boss."
            )
        else:
            response = "Which medicine are you skipping, boss?"
        _log(prompt, response, "medicine")
        return jsonify({"response": response, "mode": "medicine"})


def _cmd_med_add(prompt, p_lower):
    if any(t in p_lower for t in MED_ADD_TRIGGERS) and medicine_tracker and friday_brain:
        import re as medrex
        extract = friday_brain.think(
            f"Extract medicine tracking info from: '{prompt}'\n"
            f"Reply as JSON: {{\"name\": str, \"times\": [\"HH:MM\"], \"dosage\": str}}\n"
            f"If time isn't specified, use a reasonable default "
            f"like [\"08:00\"]. JSON only.",
            raw=True,
        )
        try:
            clean = medrex.sub(r"```json|```", "", extract["response"]).strip()
            data = json.loads(clean)
            result = medicine_tracker.add_medicine(
                data.get("name", ""),
                data.get("times", ["08:00"]),
                data.get("dosage", ""),
            )
            response = (
                f"Added {result['name']} to your schedule, boss. "
                f"I'll remind you."
            )
        except Exception:
            response = (
                "What medicine, and what time should I remind "
                "you, boss?"
            )
        _log(prompt, response, "medicine")
        return jsonify({"response": response, "mode": "medicine"})


def _cmd_homekit(prompt, p_lower):
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


def _cmd_mac_app(prompt, p_lower):
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


def _cmd_ha_status(prompt, p_lower):
    if HA_OK and home_assistant and any(t in p_lower for t in HA_STATUS_TRIGGERS):
        result = home_assistant.get_states()
        if "error" in result:
            response = "Home Assistant isn't reachable right now, boss."
        else:
            # "remote" entities duplicate their paired media_player's
            # friendly name (e.g. the TV's remote.* and media_player.*
            # both read "LivingRm (UN50NU6950)") — skip them so the
            # readout doesn't repeat the same device twice.
            devices = [
                {"name": e.get("attributes", {}).get("friendly_name", e["entity_id"]), "state": e["state"]}
                for e in result["states"]
                if e["entity_id"].split(".")[0] != "remote"
            ]
            lines = [f"{d['name']} is {d['state']}" for d in devices]
            response = "Here's what Home Assistant sees, boss: " + "; ".join(lines) + "."
            spawn_widget("data", {"title": "HOME ASSISTANT", "rows": devices})
        _log(prompt, response, "home_assistant")
        return jsonify({"response": response, "mode": "home_assistant"})


def _cmd_ha_toggle(prompt, p_lower):
    if HA_OK and home_assistant and ("turn on" in p_lower or "turn off" in p_lower):
        for device_name, entity_id in HA_DEVICE_TRIGGERS.items():
            if device_name in p_lower:
                domain = entity_id.split(".")[0]
                service = "turn_on" if "turn on" in p_lower else "turn_off"
                result = home_assistant.call_service(domain, service, entity_id)
                if "error" in result:
                    response = "Home Assistant isn't reachable right now, boss."
                else:
                    verb = "on" if service == "turn_on" else "off"
                    response = f"Done, boss. Turning the {device_name} {verb}."
                _log(prompt, response, "home_assistant")
                return jsonify({"response": response, "mode": "home_assistant"})


def _cmd_jarvis_proxy(prompt, p_lower):
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


# A message with none of these is certainly a single request, so the
# common case never pays for an extra LLM round trip.
_MULTI_HINT = re.compile(r",|;| and | then | also | plus ", re.I)


def _split_commands(prompt: str) -> list[str]:
    """Split a message carrying several distinct requests.

    The dispatch chain returns on its first match, so "run a self repair,
    can you read my Gmail, and remind me to take my vitamins at 8am" ran
    the self-repair and silently dropped the other two -- three handlers
    matched, one executed, no indication the rest were skipped.

    Splitting is done by the model rather than by punctuation, because
    punctuation is genuinely ambiguous here: "email Jane, Bob and Sam
    about the meeting" is one request whose commas must not be cut, while
    the example above is three. A regex confident enough to separate
    those would break working commands, which is worse than the bug.

    Fails closed in every uncertain case -- any error, any malformed
    reply, or a split whose pieces don't reconstruct the original returns
    [prompt], i.e. exactly today's behavior."""
    if not _MULTI_HINT.search(prompt) or not friday_brain:
        return [prompt]

    try:
        raw = friday_brain.think(
            "Split this message into the separate requests it contains.\n\n"
            f"Message: {prompt}\n\n"
            'Reply as JSON: {"requests": [str, ...]}\n\n'
            "One entry per distinct thing being asked for. Keep each "
            "entry's original wording so it can be acted on by itself. "
            "Most messages are a single request -- return one entry then. "
            "Commas inside one request (a list of recipients, a list of "
            "items) are NOT separate requests. JSON only.",
            raw=True,
        )["response"]
        parts = [p.strip() for p in _json_from_model(raw).get("requests", []) if str(p).strip()]
    except Exception as e:
        logging.warning(f"[multi] split failed, treating as one request: {e}")
        return [prompt]

    if len(parts) < 2:
        return [prompt]

    # Guard against a model that paraphrases or invents: every piece has
    # to be recognisable in the original, or the segments would be acted
    # on as requests the boss never actually made.
    low = prompt.lower()
    if not all(p.lower() in low for p in parts):
        logging.warning("[multi] split pieces are not verbatim; treating as one request")
        return [prompt]

    return parts


def _run_segments(segments: list[str]):
    """Run each request in turn and report every outcome.

    In order, not concurrently: "add a task and then show my list" only
    makes sense sequentially, and two handlers touching the same store at
    once is a real way to lose a write.

    One failing segment doesn't abandon the rest -- the boss asked for
    all of them, and a silent stop after the second is the same class of
    problem this whole feature exists to fix."""
    lines, modes = [], []
    for seg in segments:
        try:
            resp = _handle_prompt(seg, allow_split=False)
            body = resp[0] if isinstance(resp, tuple) else resp
            payload = body.get_json() if hasattr(body, "get_json") else {}
            text = (payload.get("response") or "").strip()
            modes.append(payload.get("mode", "friday"))
        except Exception as e:
            logging.warning(f"[multi] segment failed: {seg!r}: {e}")
            text = f"Couldn't do that one, boss: {seg}"
            modes.append("error")
        lines.append(text or f"Nothing came back for: {seg}")

    combined = "\n\n".join(lines)
    _log(" | ".join(segments), combined, "multi")
    audio_file = friday_speak(combined) if VOICE_OK else None
    return jsonify({
        "response": combined, "mode": "multi",
        "segments": segments, "segment_modes": modes,
        "has_audio": bool(audio_file), "audio_file": audio_file,
    })


@app.route("/command", methods=["POST"])
def command():
    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt", "") or "").strip()
    if not prompt:
        return jsonify({"response": "Say something, boss."})
    return _handle_prompt(prompt)


def _handle_prompt(prompt, allow_split=True):
    """The whole dispatch chain for one request.

    Split out of command() so a message carrying several requests can run
    each one through it in turn (see _split_commands). allow_split=False
    on those re-entries, so a segment can't be split again -- and so the
    safety gates below, which are about the message as a whole, run once
    against the original text rather than per fragment.
    """
    try:
        # ── Suit Lockdown — checked before EVERYTHING else, including Mayday.
        # While locked, the only thing this system will do with any message
        # is compare it to ENDGAME_PASSPHRASE — no trigger word, no prefix
        # stripping (see services/suit_lockdown.py's docstring for why that
        # used to be the actual bug). Anything else gets the same generic
        # "system locked" reply, so a stolen device can't fish for behavior
        # differences to guess the passphrase. ─────────────────────────────
        result = _cmd_lockdown_locked(prompt)
        if result is not None:
            return result

        result = _cmd_lockdown_trigger(prompt)
        if result is not None:
            return result

        # ── Mayday — no LLM call, responds immediately ────────────────────────
        result = _cmd_mayday(prompt)
        if result is not None:
            return result

        # After the real safety handlers above -- an exact trigger has
        # already returned by here, so this only sees near misses.
        result = _cmd_safety_near_miss(prompt, prompt.lower())
        if result is not None:
            return result

        # ── Safe check-in — no LLM call, stands down any pending escalation.
        # confirm_safe() already speaks its own line via friday_voice.speak()
        # (same as autonomous_agent._alert()'s convention of speaking
        # directly rather than through the HTTP response) so this doesn't
        # also generate a second, redundant audio_file for the HUD to play. ─
        result = _cmd_safe_checkin(prompt)
        if result is not None:
            return result

        result = _cmd_security_screen(prompt)
        if result is not None:
            return result

        # Several requests in one message. Deliberately placed after the
        # safety gates above -- those judge the whole message, and a
        # splitter running first could hand them fragments that read
        # differently than the original.
        if allow_split:
            segments = _split_commands(prompt)
            if len(segments) > 1:
                return _run_segments(segments)

        # Learn from every request up front (not gated behind any one
        # response branch) so it applies regardless of which handler below
        # ends up serving it.
        result = _cmd_learn_voice_mode(prompt)
        if result is not None:
            return result

        # Dark mode — zero external connectivity, local-only responses
        result = _cmd_dark_mode(prompt)
        if result is not None:
            return result

        # MCU capabilities — checked before the JARVIS proxy since these are
        # specifically FRIDAY's own named abilities, not generic chat that
        # should default to JARVIS when he's reachable.
        result = _cmd_capabilities(prompt)
        if result is not None:
            return result

        # Second-brain / news / relationships / code intents — same tier as
        # CAPABILITY_MAP above: FRIDAY's own named abilities, checked before
        # the JARVIS proxy for the same reason.
        p_lower = prompt.lower()

        result = _cmd_weather(prompt, p_lower)
        if result is not None:
            return result

        result = _cmd_news(prompt, p_lower)
        if result is not None:
            return result

        result = _cmd_translate(prompt, p_lower)
        if result is not None:
            return result

        result = _cmd_code_review(prompt, p_lower)
        if result is not None:
            return result

        result = _cmd_remember_this(prompt, p_lower)
        if result is not None:
            return result

        # "people brief on " — deliberately avoids the substring "intel on":
        # CAPABILITY_MAP already has an "intel on" trigger (government_intel(),
        # checked above this block) that matches as a substring anywhere in
        # the prompt, so any phrase containing "intel on" — even prefixed —
        # would still be unreachable.
        result = _cmd_people_brief(prompt, p_lower)
        if result is not None:
            return result

        # ── Caller intelligence ──────────────────────────────────────────────
        result = _cmd_caller_id(prompt, p_lower)
        if result is not None:
            return result

        # ── FRIDAY initiates a call ───────────────────────────────────────────
        result = _cmd_call_initiate(prompt, p_lower)
        if result is not None:
            return result

        # ── FRIDAY sends a real text (Twilio) ────────────────────────────────
        result = _cmd_sms_send(prompt, p_lower)
        if result is not None:
            return result

        # ── Catch-up brief ────────────────────────────────────────────────────
        result = _cmd_catchup(prompt, p_lower)
        if result is not None:
            return result

        # ── Focus / Pomodoro timer ────────────────────────────────────────────
        result = _cmd_focus(prompt, p_lower)
        if result is not None:
            return result

        # ── Habit logging ─────────────────────────────────────────────────────
        result = _cmd_habit_log(prompt, p_lower)
        if result is not None:
            return result

        # ── Journal ───────────────────────────────────────────────────────────
        result = _cmd_journal(prompt, p_lower)
        if result is not None:
            return result

        # ── Probability assessment ────────────────────────────────────────────
        result = _cmd_probability(prompt, p_lower)
        if result is not None:
            return result

        # ── Recognizance ─────────────────────────────────────────────────────
        result = _cmd_recon(prompt, p_lower)
        if result is not None:
            return result

        # ── System doctor ────────────────────────────────────────────────────
        result = _cmd_diagnostics(prompt, p_lower)
        if result is not None:
            return result

        # ── Self-repair: diagnose/fix/sandbox-test/confirm her own bugs ────────
        result = _cmd_self_repair(prompt, p_lower)
        if result is not None:
            return result

        # ── Cross-check with JARVIS ────────────────────────────────────────────
        result = _cmd_cross_check(prompt, p_lower)
        if result is not None:
            return result

        # ── Combat / normal mode ──────────────────────────────────────────────
        result = _cmd_combat_mode(prompt, p_lower)
        if result is not None:
            return result

        result = _cmd_normal_mode(prompt, p_lower)
        if result is not None:
            return result

        # ── Priority focus ────────────────────────────────────────────────────
        result = _cmd_priority(prompt, p_lower)
        if result is not None:
            return result

        # ── Travel intel ──────────────────────────────────────────────────────
        result = _cmd_travel(prompt, p_lower)
        if result is not None:
            return result

        # ── Spotify direct control ────────────────────────────────────────────
        result = _cmd_spotify_stop(prompt, p_lower)
        if result is not None:
            return result

        result = _cmd_spotify_play(prompt, p_lower)
        if result is not None:
            return result

        # ── Calendar: create an event ─────────────────────────────────────────
        result = _cmd_calendar_add(prompt, p_lower)
        if result is not None:
            return result

        # ── Goals ─────────────────────────────────────────────────────────────
        result = _cmd_goal_report(prompt, p_lower)
        if result is not None:
            return result

        result = _cmd_goal_add(prompt, p_lower)
        if result is not None:
            return result

        # Left out of the source spec's command() wiring entirely (the
        # trigger list was declared but never actually checked) — without
        # this, "worked on X" would never log progress, which defeats the
        # whole point of tracking goals automatically.
        result = _cmd_goal_progress(prompt, p_lower)
        if result is not None:
            return result

        # ── Email: draft / triage (checked before EMAIL_TRIGGERS — that
        # list's bare "inbox"/"what emails" are substrings of these
        # phrases and would otherwise always win first) ────────────────────
        result = _cmd_email_draft(prompt, p_lower)
        if result is not None:
            return result

        # ── Email: send the pending draft ("send it") ───────────────────────
        result = _cmd_email_send(prompt, p_lower)
        if result is not None:
            return result

        # ── Email: compose and send directly, no draft step ─────────────────
        result = _cmd_email_compose_send(prompt, p_lower)
        if result is not None:
            return result

        result = _cmd_email_triage(prompt, p_lower)
        if result is not None:
            return result

        # ── Email ─────────────────────────────────────────────────────────────
        result = _cmd_email_summary(prompt, p_lower)
        if result is not None:
            return result

        # ── Note that ─────────────────────────────────────────────────────────
        result = _cmd_note(prompt, p_lower)
        if result is not None:
            return result

        # ── Create a file (checked before recall — "open the file" etc.
        # never mentions "create", so there's no overlap either way) ────────
        result = _cmd_create_file(prompt, p_lower)
        if result is not None:
            return result

        result = _cmd_file_recall(prompt, p_lower)
        if result is not None:
            return result

        # ── Reminders ─────────────────────────────────────────────────────────
        result = _cmd_reminder(prompt, p_lower)
        if result is not None:
            return result

        # ── Task list ─────────────────────────────────────────────────────────
        result = _cmd_task_show(prompt, p_lower)
        if result is not None:
            return result

        result = _cmd_task_add(prompt, p_lower)
        if result is not None:
            return result

        # ── Medicine tracker ─────────────────────────────────────────────────
        result = _cmd_med_schedule(prompt, p_lower)
        if result is not None:
            return result

        result = _cmd_med_taken(prompt, p_lower)
        if result is not None:
            return result

        result = _cmd_med_skip(prompt, p_lower)
        if result is not None:
            return result

        result = _cmd_med_add(prompt, p_lower)
        if result is not None:
            return result

        # ── Smart home via HomeKit (Shortcuts run on the Mac Bridge) ──────────
        result = _cmd_homekit(prompt, p_lower)
        if result is not None:
            return result

        # ── Open a Mac app via Mac Bridge ──────────────────────────────────────
        result = _cmd_mac_app(prompt, p_lower)
        if result is not None:
            return result

        # ── Home Assistant — status ─────────────────────────────────────────
        result = _cmd_ha_status(prompt, p_lower)
        if result is not None:
            return result

        # ── Home Assistant — generic turn on/off <device> ───────────────────
        result = _cmd_ha_toggle(prompt, p_lower)
        if result is not None:
            return result

        # Proxy to JARVIS if online and not in coverage mode
        result = _cmd_jarvis_proxy(prompt, p_lower)
        if result is not None:
            return result

        # Nothing claimed it, but a real trigger phrase matched -- so a
        # handler wanted this and declined, almost always because the
        # service behind it is unavailable (25 handlers gate their
        # trigger check on `and <service>`, and return None when it's
        # missing).
        #
        # Falling through to the model here is what produced the worst
        # answers of this whole branch: "I'm not able to access your
        # Gmail account" while IMAP was working, and "Self repair
        # initiated, boss" when self-repair hadn't loaded and nothing
        # ran at all. The model has no idea what FRIDAY can do, so it
        # invents in whichever direction sounds plausible.
        #
        # Saying "that isn't available right now" is a worse answer than
        # doing the thing, and a far better one than pretending to.
        unavailable = _matched_but_unavailable(p_lower)
        if unavailable:
            response = (f"I'd normally handle that ({unavailable}), boss, but that "
                        f"system isn't available right now — so I haven't done anything.")
            logging.warning(f"[dispatch] {unavailable} matched but its handler declined")
            _log(prompt, response, "unavailable")
            return jsonify({"response": response, "mode": "unavailable",
                             "feature": unavailable})

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

                # Conversation-turn recall (keyword-matched past exchanges)
                # is the one context source core/memory_hub.py doesn't cover
                # -- kept as its own lookup here, and deliberately the most
                # generic signal, so it sits last in the prepend order below.
                try:
                    from core.friday_memory import recall as recall_conversations
                    recalled = recall_conversations(prompt, 3)
                except Exception:
                    recalled = []
                context = f"Recent relevant: {' | '.join(recalled)}" if recalled else ""

                if TRAINING_OK:
                    knowledge = friday_trainer.get_context_brief(prompt)
                    if knowledge:
                        context = "\n".join(filter(None, [knowledge, context]))

                # core/memory_hub.py's unified recall() -- facts, notes,
                # second_brain, continuity's unresolved topics, and (via
                # services/wisdom.py) decisions/reading/journal, all ranked
                # together. Replaces the old separate get_context_for()
                # facts lookup and standalone wisdom lookup that used to
                # live here -- both were subsets of what this one call
                # already covers, so calling both was redundant, not
                # additive. Prepended, not appended — _build_messages()
                # truncates context to its first 500 chars, so this
                # query-specific, already-ranked signal needs to survive
                # that cut ahead of the more generic context above.
                try:
                    from core.memory_hub import recall as recall_memory
                    hits = recall_memory(prompt, limit=5)
                    if hits:
                        memory_context = "; ".join(h["text"] for h in hits)
                        context = "\n".join(filter(None, [memory_context, context]))
                except Exception as e:
                    logging.warning(f"Memory hub recall failed: {e}")

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
        # Was a bare swallow with no logging, so any crash in the whole
        # dispatch chain vanished behind "I'm here, boss" with nothing
        # recorded -- the same opaque-failure shape that made the SMTP
        # and calendar bugs take several passes each. The reply to the
        # boss stays deliberately calm; the traceback goes to the log.
        logging.exception(f"[command] unhandled error on prompt: {prompt[:200]!r}")
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


# ── Entry ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logging.info(f"{FRIDAY_NAME} V{FRIDAY_VERSION} starting on port {port}")
    app.run(host="0.0.0.0", port=port)
