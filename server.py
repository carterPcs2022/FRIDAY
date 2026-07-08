"""FRIDAY V2 — complete server. Flask + emotional intelligence + JARVIS
monitoring + green HUD + voice-mode control."""
import time
from flask import Flask, jsonify

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
    from core.friday_capabilities import CAPABILITY_MAP
    CAPABILITIES_OK = True
except Exception as e:
    CAPABILITY_MAP = {}
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

        if SECURITY_OK:
            screen = friday_security.screen_request(friday_security.client_ip(request), prompt)
            if screen.get("blocked"):
                return jsonify({"response": "Request blocked.", "blocked": True}), 403

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
<title>F.R.I.D.A.Y V2</title>
<style>
:root {
  --bg:     #010d06;
  --panel:  rgba(0,255,128,0.03);
  --border: rgba(0,255,128,0.15);
  --accent: #00ff80;
  --a2:     #00ffcc;
  --warn:   #ffaa00;
  --danger: #ff4444;
  --text:   #ccffe0;
  --muted:  #2a5a40;
  --grid:   rgba(0,255,128,0.025);
}
* { box-sizing:border-box; margin:0; padding:0; }
body {
  background: var(--bg);
  background-image:
    linear-gradient(var(--grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid) 1px, transparent 1px);
  background-size: 48px 48px;
  color: var(--text);
  font-family: 'Courier New', monospace;
  height: 100vh;
  overflow: hidden;
}
body::after {
  content:'';
  position:fixed; inset:0;
  background: repeating-linear-gradient(
    0deg, transparent, transparent 3px,
    rgba(0,0,0,0.015) 3px, rgba(0,0,0,0.015) 4px
  );
  pointer-events:none; z-index:9999;
}
.corner {
  position:fixed; width:20px; height:20px;
  z-index:9998; pointer-events:none;
}
.c-tl { top:8px; left:8px;
  border-top:2px solid rgba(0,255,128,0.3);
  border-left:2px solid rgba(0,255,128,0.3); }
.c-tr { top:8px; right:8px;
  border-top:2px solid rgba(0,255,128,0.3);
  border-right:2px solid rgba(0,255,128,0.3); }
.c-bl { bottom:8px; left:8px;
  border-bottom:2px solid rgba(0,255,128,0.3);
  border-left:2px solid rgba(0,255,128,0.3); }
.c-br { bottom:8px; right:8px;
  border-bottom:2px solid rgba(0,255,128,0.3);
  border-right:2px solid rgba(0,255,128,0.3); }

.layout {
  display: grid;
  grid-template-rows: 52px 1fr 42px;
  grid-template-columns: 240px 1fr 280px;
  height: 100vh;
  position: relative; z-index:1;
}

header {
  grid-column: 1/-1;
  display: flex; align-items:center; padding: 0 18px;
  gap: 18px;
  background: rgba(1,13,6,0.98);
  border-bottom: 1px solid var(--border);
  position: relative;
}
header::after {
  content:''; position:absolute;
  bottom:0; left:0; right:0; height:1px;
  background: linear-gradient(90deg,
    transparent, var(--accent), var(--a2),
    var(--accent), transparent);
  opacity:0.4;
}
.logo-ring {
  width:36px; height:36px; border-radius:50%;
  border:2px solid var(--accent);
  display:flex; align-items:center; justify-content:center;
  box-shadow: 0 0 14px rgba(0,255,128,0.3),
              inset 0 0 14px rgba(0,255,128,0.08);
}
.logo-ring-inner {
  width:20px; height:20px; border-radius:50%;
  background: radial-gradient(circle,
    rgba(0,255,128,0.5) 0%, transparent 70%);
  animation: ring-pulse 3s ease-in-out infinite;
}
@keyframes ring-pulse {
  0%,100% { opacity:0.5; transform:scale(0.9); }
  50%      { opacity:1;   transform:scale(1.1); }
}
.logo { font-size:20px; font-weight:900; letter-spacing:8px;
  color:var(--accent);
  text-shadow:0 0 16px rgba(0,255,128,0.4); }
.logo-sub { font-size:8px; letter-spacing:3px;
  color:var(--muted); margin-top:2px; }
.header-stats {
  flex:1; display:flex; align-items:center;
  justify-content:center; gap:20px;
}
.h-stat { display:flex; flex-direction:column;
  align-items:center; gap:2px; }
.h-stat-val { font-size:12px; color:var(--text);
  letter-spacing:1px; }
.h-stat-lbl { font-size:8px; letter-spacing:2px;
  color:var(--muted); }
.hdiv { width:1px; height:24px; background:var(--border); }
.header-right { display:flex; align-items:center;
  gap:10px; margin-left:auto; }
.status-pill {
  display:flex; align-items:center; gap:6px;
  padding:3px 10px; border:1px solid var(--border);
  border-radius:2px; font-size:9px; letter-spacing:2px;
}
.s-dot { width:6px; height:6px; border-radius:50%;
  background:var(--accent); box-shadow:0 0 6px var(--accent);
  animation:sdot 2.5s ease-in-out infinite; }
@keyframes sdot {0%,100%{opacity:1}50%{opacity:0.3}}
.s-dot.w { background:var(--warn); box-shadow:0 0 6px var(--warn); }
.mode-badge {
  font-size:9px; letter-spacing:2px; color:var(--a2);
  padding:3px 8px; border:1px solid rgba(0,255,204,0.2);
  border-radius:2px; }
.time-disp { font-size:13px; letter-spacing:2px;
  color:var(--muted); }
.ambient-btn {
  padding:3px 10px; border:1px solid var(--border);
  border-radius:2px; background:transparent;
  color:var(--muted); font-family:inherit;
  font-size:9px; letter-spacing:2px; cursor:pointer; }
.ambient-btn.on {
  border-color:var(--accent); color:var(--accent);
  background:rgba(0,255,128,0.06); }

.panel {
  background:var(--panel); border:1px solid var(--border);
  border-radius:2px; position:relative;
}
.panel::before,
.panel::after {
  content:''; position:absolute;
  width:8px; height:8px;
}
.panel::before {
  top:-1px; left:-1px;
  border-top:2px solid var(--accent);
  border-left:2px solid var(--accent);
}
.panel::after {
  bottom:-1px; right:-1px;
  border-bottom:2px solid var(--accent);
  border-right:2px solid var(--accent);
}
.panel-glow::after {
  content:''; position:absolute;
  top:0; left:10%; right:10%; height:1px;
  background:linear-gradient(90deg,
    transparent, var(--accent), transparent);
  opacity:0.4;
}
.panel-title {
  font-size:8px; letter-spacing:4px; color:var(--muted);
  padding:8px 12px 5px;
  border-bottom:1px solid rgba(0,255,128,0.06);
  display:flex; justify-content:space-between;
}

.left-col {
  display:flex; flex-direction:column; gap:7px;
  padding:8px 8px 8px 10px; overflow-y:auto;
  scrollbar-width:none;
  border-right:1px solid rgba(0,255,128,0.06);
}
.left-col::-webkit-scrollbar { display:none; }

.diag-item {
  padding:5px 12px;
  border-bottom:1px solid rgba(0,255,128,0.04);
}
.diag-item:last-child { border-bottom:none; }
.diag-hdr { display:flex; justify-content:space-between;
  margin-bottom:5px; font-size:9px; }
.diag-lbl { color:var(--muted); letter-spacing:1px; }
.diag-val { color:var(--text); font-weight:700; }
.diag-val.w { color:var(--warn); }
.diag-val.d { color:var(--danger); }
.bar { height:2px; background:rgba(0,255,128,0.08);
  border-radius:1px; overflow:hidden; }
.bar-fill {
  height:100%; border-radius:1px;
  background:linear-gradient(90deg,
    rgba(0,200,80,0.8), var(--accent));
  box-shadow:0 0 5px rgba(0,255,128,0.4);
  transition:width 1s ease;
}
.bar-fill.w {
  background:linear-gradient(90deg,#cc5500,var(--warn)); }
.bar-fill.d {
  background:linear-gradient(90deg,#990000,var(--danger)); }

.stat-row {
  display:flex; justify-content:space-between;
  padding:4px 12px; font-size:10px;
  border-bottom:1px solid rgba(0,255,128,0.04);
}
.stat-row:last-child { border-bottom:none; }
.stat-lbl { color:var(--muted); }
.stat-val { color:var(--text); }
.stat-val.green  { color:var(--accent); }
.stat-val.warn   { color:var(--warn); }
.stat-val.danger { color:var(--danger); }

.sentinel-num {
  font-size:34px; font-weight:900; line-height:1;
  color:var(--accent);
  text-shadow:0 0 16px rgba(0,255,128,0.4);
  padding:6px 12px 2px;
}
.sentinel-num.w { color:var(--warn);
  text-shadow:0 0 16px rgba(255,170,0,0.4); }
.sentinel-num.d { color:var(--danger);
  text-shadow:0 0 16px rgba(255,68,68,0.4); }

.center-col {
  display:flex; flex-direction:column;
  padding:8px; gap:7px; min-height:0;
}
.ctrl-bar { display:flex; gap:5px; flex-shrink:0; }
.ctrl-btn {
  padding:4px 12px; border:1px solid var(--border);
  border-radius:2px; background:transparent;
  color:var(--muted); font-family:inherit;
  font-size:9px; letter-spacing:2px; cursor:pointer;
}
.ctrl-btn:hover { border-color:var(--accent); color:var(--accent); }
.ctrl-btn.ml { margin-left:auto; }

.msgs {
  flex:1; overflow-y:auto; padding:3px 1px;
  display:flex; flex-direction:column; gap:1px;
  min-height:0;
}
.msgs::-webkit-scrollbar { width:3px; }
.msgs::-webkit-scrollbar-thumb { background:var(--muted); }
.msg { padding:8px 12px;
  border-left:2px solid transparent;
  animation:msg-in 0.2s ease; }
@keyframes msg-in {
  from{opacity:0;transform:translateY(3px)}
  to{opacity:1;transform:translateY(0)} }
.msg-you { border-left-color:var(--a2);
  background:rgba(0,255,204,0.02); }
.msg-fri { border-left-color:var(--accent);
  background:rgba(0,255,128,0.02); }
.msg-sys { border-left-color:var(--muted);
  background:transparent; }
.msg-who { font-size:8px; letter-spacing:3px;
  margin-bottom:4px; }
.msg-you .msg-who  { color:var(--a2); }
.msg-fri .msg-who  { color:var(--accent); }
.msg-sys .msg-who  { color:var(--muted); }
.msg-txt { font-size:12px; line-height:1.65; }
.msg-you .msg-txt  { color:var(--a2); }
.msg-fri .msg-txt  { color:var(--text); }
.msg-sys .msg-txt  { color:var(--muted); font-style:italic; font-size:10px; }
.msg-meta { display:flex; gap:8px; margin-top:4px; }
.msg-model { font-size:8px; color:var(--muted);
  padding:1px 5px; border:1px solid var(--border);
  border-radius:1px; letter-spacing:1px; }
.msg-ms { font-size:8px; color:var(--muted); }
.think { display:flex; gap:6px; align-items:center;
  padding:8px 12px; font-size:9px; letter-spacing:2px;
  color:var(--muted); border-left:2px solid var(--accent); }
.tdot { width:4px; height:4px; border-radius:50%;
  background:var(--accent);
  animation:sdot 0.8s ease-in-out infinite; }
.tdot:nth-child(2){animation-delay:0.2s}
.tdot:nth-child(3){animation-delay:0.4s}

.input-row { display:flex; gap:7px; flex-shrink:0; }
.inp {
  flex:1; background:rgba(0,255,128,0.02);
  border:1px solid var(--border); border-radius:2px;
  color:var(--text); padding:9px 14px;
  font-family:inherit; font-size:12px; outline:none;
  transition:border-color 0.2s, box-shadow 0.2s;
}
.inp:focus {
  border-color:var(--accent);
  box-shadow:0 0 0 1px rgba(0,255,128,0.12),
             inset 0 0 16px rgba(0,255,128,0.03);
}
.inp::placeholder { color:var(--muted); }
.send-btn {
  padding:0 16px; background:rgba(0,255,128,0.06);
  border:1px solid var(--accent); border-radius:2px;
  color:var(--accent); font-family:inherit;
  font-size:9px; letter-spacing:3px; cursor:pointer;
}
.send-btn:hover { background:rgba(0,255,128,0.12); }
.mic-btn {
  width:40px; background:transparent;
  border:1px solid var(--border); border-radius:2px;
  color:var(--muted); font-size:14px; cursor:pointer;
}
.mic-btn.on { border-color:var(--a2); color:var(--a2); }

.right-col {
  display:flex; flex-direction:column; gap:7px;
  padding:8px 10px 8px 8px; overflow-y:auto;
  scrollbar-width:none;
  border-left:1px solid rgba(0,255,128,0.06);
}
.right-col::-webkit-scrollbar { display:none; }

.voice-name { font-size:13px; font-weight:700;
  letter-spacing:2px; color:var(--accent); margin-bottom:5px; }
.voice-track { height:2px;
  background:rgba(0,255,128,0.08); border-radius:1px;
  overflow:hidden; margin-bottom:4px; }
.voice-fill {
  height:100%;
  background:linear-gradient(90deg, rgba(0,200,80,0.8), var(--a2));
  transition:width 1s ease; }
.voice-chars { display:flex; justify-content:space-between;
  font-size:8px; color:var(--muted); margin-bottom:8px; }
.voice-btns { display:flex; gap:5px; }
.vbtn {
  flex:1; padding:4px 0; border:1px solid var(--border);
  border-radius:2px; background:transparent;
  color:var(--muted); font-family:inherit;
  font-size:8px; letter-spacing:1px; cursor:pointer; }
.vbtn.on { border-color:var(--accent); color:var(--accent); }
.mute-btn {
  padding:4px 10px; border:1px solid var(--border);
  border-radius:2px; background:transparent;
  color:var(--muted); font-family:inherit;
  font-size:8px; letter-spacing:2px; cursor:pointer; }
.mute-btn.on { border-color:var(--warn); color:var(--warn); }

.alert-item {
  display:flex; gap:7px; align-items:flex-start;
  padding:5px 0; border-bottom:1px solid rgba(0,255,128,0.04);
  font-size:10px;
}
.alert-item:last-child { border-bottom:none; }
.adot { width:5px; height:5px; border-radius:50%;
  margin-top:3px; flex-shrink:0; }
.adot.d { background:var(--danger); box-shadow:0 0 4px var(--danger); }
.adot.w { background:var(--warn);   box-shadow:0 0 4px var(--warn); }
.adot.i { background:var(--accent); box-shadow:0 0 4px var(--accent); }
.alert-txt { color:var(--text); line-height:1.4; }

.con-text {
  padding:8px 12px 10px; font-size:10px;
  line-height:1.8; color:var(--muted); font-style:italic;
  border-left:2px solid rgba(0,255,128,0.15);
  margin:0 12px 8px; background:rgba(0,255,128,0.015);
}

.ver-status {
  padding:8px 12px 10px;
}
.ver-item {
  display:flex; justify-content:space-between;
  padding:3px 0; font-size:10px;
  border-bottom:1px solid rgba(0,255,128,0.04);
}
.ver-item:last-child { border-bottom:none; }
.ver-nominal { color:var(--accent); }
.ver-warn    { color:var(--warn); }
.ver-danger  { color:var(--danger); }

footer {
  grid-column:1/-1; display:flex; align-items:center;
  padding:0 14px; gap:5px;
  background:rgba(1,13,6,0.98);
  border-top:1px solid var(--border);
}
.scene-btn {
  padding:3px 10px; border:1px solid rgba(0,255,128,0.1);
  border-radius:1px; background:transparent;
  color:var(--muted); font-family:inherit;
  font-size:8px; letter-spacing:2px; cursor:pointer;
  text-decoration:none; display:flex; align-items:center;
}
.scene-btn:hover {
  border-color:var(--accent); color:var(--accent); }
.f-right { margin-left:auto; display:flex;
  align-items:center; gap:14px;
  font-size:8px; letter-spacing:2px; }
.f-status { display:flex; align-items:center; gap:4px;
  color:var(--muted); }
.f-dot { width:5px; height:5px; border-radius:50%; }
.f-dot.g { background:var(--accent); box-shadow:0 0 4px var(--accent); }
.f-dot.y { background:var(--warn);   box-shadow:0 0 4px var(--warn); }
.f-dot.r { background:var(--danger); box-shadow:0 0 4px var(--danger); }

.cov-banner {
  background:rgba(255,170,0,0.06);
  border:1px solid rgba(255,170,0,0.25);
  border-radius:2px; padding:5px 10px;
  font-size:9px; letter-spacing:2px; color:var(--warn);
  display:none;
}
.cov-banner.on { display:block; }
</style>
</head>
<body>

<div class="corner c-tl"></div>
<div class="corner c-tr"></div>
<div class="corner c-bl"></div>
<div class="corner c-br"></div>

<div class="layout">

<header>
  <div class="logo-ring">
    <div class="logo-ring-inner"></div>
  </div>
  <div>
    <div class="logo">F.R.I.D.A.Y</div>
    <div class="logo-sub" id="mark-lbl">V2 — LOADING</div>
  </div>
  <div class="header-stats">
    <div class="h-stat">
      <div class="h-stat-val" id="h-cpu">—%</div>
      <div class="h-stat-lbl">SYSTEMS</div>
    </div>
    <div class="hdiv"></div>
    <div class="h-stat">
      <div class="h-stat-val" id="h-ram">—%</div>
      <div class="h-stat-lbl">MEMORY</div>
    </div>
    <div class="hdiv"></div>
    <div class="h-stat">
      <div class="h-stat-val" id="h-up">—</div>
      <div class="h-stat-lbl">UPTIME</div>
    </div>
    <div class="hdiv"></div>
    <div class="h-stat">
      <div class="h-stat-val" id="h-jar">—</div>
      <div class="h-stat-lbl">JARVIS</div>
    </div>
  </div>
  <div class="header-right">
    <div class="status-pill">
      <div class="s-dot" id="s-dot"></div>
      <span id="s-txt">CONNECTING</span>
    </div>
    <div class="mode-badge" id="mode-badge">NORMAL</div>
    <div class="time-disp" id="clock">--:--:--</div>
    <button class="ambient-btn" id="amb-btn"
            onclick="toggleAmbient()">⚡ AMBIENT</button>
  </div>
</header>

<div class="left-col">

  <div class="panel panel-glow">
    <div class="panel-title">DIAGNOSTICS <span>F.R.I.D.A.Y</span></div>
    <div style="padding:6px 0">
      <div class="diag-item">
        <div class="diag-hdr">
          <span class="diag-lbl">CPU</span>
          <span class="diag-val" id="cpu-v">—%</span>
        </div>
        <div class="bar">
          <div class="bar-fill" id="cpu-b" style="width:0%"></div>
        </div>
      </div>
      <div class="diag-item">
        <div class="diag-hdr">
          <span class="diag-lbl">MEMORY</span>
          <span class="diag-val" id="ram-v">—%</span>
        </div>
        <div class="bar">
          <div class="bar-fill" id="ram-b" style="width:0%"></div>
        </div>
      </div>
      <div class="diag-item">
        <div class="diag-hdr">
          <span class="diag-lbl">UPTIME</span>
          <span class="diag-val green" id="up-v">—</span>
        </div>
      </div>
      <div class="diag-item">
        <div class="diag-hdr">
          <span class="diag-lbl">API CALLS</span>
          <span class="diag-val" id="api-v">—</span>
        </div>
      </div>
    </div>
  </div>

  <div class="panel">
    <div class="panel-title">SECURITY</div>
    <div class="sentinel-num" id="threat-num">0</div>
    <div style="padding:0 0 6px">
      <div class="stat-row">
        <span class="stat-lbl">THREATS</span>
        <span class="stat-val danger" id="st-threats">0</span>
      </div>
      <div class="stat-row">
        <span class="stat-lbl">BLOCKED IPS</span>
        <span class="stat-val danger" id="st-blocked">0</span>
      </div>
      <div class="stat-row">
        <span class="stat-lbl">VERONICA</span>
        <span class="stat-val green" id="st-veronica">ACTIVE</span>
      </div>
    </div>
  </div>

  <div class="panel">
    <div class="panel-title">JARVIS LINK</div>
    <div style="padding:6px 0">
      <div class="stat-row">
        <span class="stat-lbl">STATUS</span>
        <span class="stat-val" id="j-status">—</span>
      </div>
      <div class="stat-row">
        <span class="stat-lbl">COVERAGE</span>
        <span class="stat-val" id="j-cover">—</span>
      </div>
      <div class="stat-row">
        <span class="stat-lbl">LATENCY</span>
        <span class="stat-val green" id="j-lat">—</span>
      </div>
      <div class="stat-row">
        <span class="stat-lbl">SYNC</span>
        <span class="stat-val" id="j-sync">—</span>
      </div>
    </div>
  </div>

  <div class="panel">
    <div class="panel-title">VERONICA</div>
    <div class="ver-status" id="ver-status">
      <div class="no-data" style="font-size:10px;color:var(--muted)">
        Loading...
      </div>
    </div>
  </div>

  <div class="panel">
    <div class="panel-title">EMOTIONAL TREND</div>
    <div style="padding:8px 12px" id="emotion-trend">
      <div style="font-size:10px;color:var(--muted)">No data</div>
    </div>
  </div>

</div>

<div class="center-col">
  <div class="cov-banner" id="cov-banner">
    ⚡ COVERAGE MODE — JARVIS OFFLINE — FRIDAY IN CONTROL
  </div>
  <div class="ctrl-bar">
    <button class="ctrl-btn" onclick="sendQ('FRIDAY run a morning brief')">MORNING BRIEF</button>
    <button class="ctrl-btn" onclick="sendQ('FRIDAY device diagnostics')">DIAGNOSTICS</button>
    <button class="ctrl-btn ml" onclick="clearMsgs()">CLEAR</button>
  </div>
  <div class="msgs" id="msgs">
    <div class="msg msg-sys">
      <div class="msg-who">SYSTEM</div>
      <div class="msg-txt">F.R.I.D.A.Y online. Ready when you are, boss.</div>
    </div>
  </div>
  <div class="input-row">
    <button class="mic-btn" id="mic-btn" onclick="toggleMic()">🎤</button>
    <input class="inp" id="inp"
           placeholder="Talk to FRIDAY..."
           onkeydown="if(event.key==='Enter')send()">
    <button class="send-btn" onclick="send()">SEND</button>
  </div>
</div>

<div class="right-col">

  <div class="panel">
    <div class="panel-title">
      VOICE ENGINE
      <button class="mute-btn" id="mute-btn"
              onclick="toggleMute()">MUTE</button>
    </div>
    <div style="padding:8px 12px 10px">
      <div class="voice-name">ELEVENLABS</div>
      <div class="voice-btns">
        <button class="vbtn on" id="vb-el">ELEVEN</button>
        <button class="vbtn" id="vb-edge">EDGE</button>
        <button class="vbtn" id="vb-off">OFFLINE</button>
      </div>
    </div>
  </div>

  <div class="panel">
    <div class="panel-title">LIVE ALERTS</div>
    <div id="alerts" style="padding:6px 0">
      <div style="padding:6px 12px;font-size:10px;
                  color:var(--muted)">No alerts.</div>
    </div>
  </div>

  <div class="panel" style="flex:1;min-height:0;display:flex;flex-direction:column">
    <div class="panel-title">RECENT EXCHANGES</div>
    <div class="con-text" id="con-feed"
         style="flex:1;overflow-y:auto">
      No exchanges yet.
    </div>
  </div>

</div>

<footer>
  <button class="scene-btn" onclick="setVoiceMode('normal')">NORMAL</button>
  <button class="scene-btn" onclick="setVoiceMode('night')">NIGHT</button>
  <button class="scene-btn" onclick="setVoiceMode('focused')">FOCUS</button>
  <button class="scene-btn" onclick="setVoiceMode('support')">SUPPORT</button>
  <a href="/friday/veronica/selftest" class="scene-btn"
     target="_blank">VERONICA</a>
  <a href="/friday/protocols" class="scene-btn"
     target="_blank">PROTOCOLS</a>

  <div class="f-right">
    <div class="f-status">
      <div class="f-dot g" id="f-friday"></div>
      <span>FRIDAY</span>
    </div>
    <div class="f-status">
      <div class="f-dot" id="f-jarvis"></div>
      <span>JARVIS</span>
    </div>
    <div class="f-status">
      <div class="f-dot g" id="f-ver"></div>
      <span>VERONICA</span>
    </div>
    <div class="f-status" style="color:var(--muted)">
      COVERAGE: <span id="f-cover">OFF</span>
    </div>
  </div>
</footer>

</div>

<script>
// Same origin as the page that served this HUD — no hardcoded port. A
// fixed fallback port here would misroute behind Render's proxy (same
// bug class the previous HUD iteration fixed; not reintroducing it).
const BASE = `${location.protocol}//${location.host}`;
let muted = false, ambient = false, recording = false;
let currentAudio = null, ambientCtx = null;

function tick() {
  const t = new Date().toLocaleTimeString('en-US',{hour12:false});
  document.getElementById('clock').textContent = t;
}
setInterval(tick,1000); tick();

async function send() {
  const inp  = document.getElementById('inp');
  const text = inp.value.trim();
  if (!text) return;
  inp.value = '';
  addMsg('you','YOU',text);
  addFeed('YOU', text);
  showThink();
  try {
    const r = await fetch(`${BASE}/command`,{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({prompt:text}),
    });
    const d = await r.json();
    hideThink();
    addMsg('fri','FRIDAY',d.response||'...',{
      model: d.model||'',
      ms:    d.ms||0,
    });
    addFeed('FRIDAY', d.response || '...');
    if (!muted && d.has_audio && d.audio_file) {
      playAudio(d.audio_file);
    }
    if (d.emotion && d.emotion !== 'neutral') {
      addAlert(
        `Emotional state: ${d.emotion}`,
        'i'
      );
    }
  } catch(e) {
    hideThink();
    addMsg('sys','SYSTEM','Connection error, boss.');
  }
}

function sendQ(q) {
  document.getElementById('inp').value = q;
  send();
}

function addFeed(who, text) {
  const feed = document.getElementById('con-feed');
  const line = document.createElement('div');
  line.style.marginBottom = '6px';
  line.textContent = `${who}: ${text}`.slice(0, 160);
  feed.insertBefore(line, feed.firstChild);
  while (feed.children.length > 8) feed.removeChild(feed.lastChild);
}

function addMsg(type,label,text,meta={}) {
  const msgs = document.getElementById('msgs');
  hideThink();
  const el = document.createElement('div');
  el.className = `msg msg-${type}`;
  const clean = text
    .replace(/\[Confidence:\s*\d+%\]/gi,'')
    .replace(/_FYI:.*?_/gi,'')
    .replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>')
    .replace(/\*(.*?)\*/g,'<em>$1</em>');
  let metaHtml = '';
  if (meta.model) {
    metaHtml = `<div class="msg-meta">
      <span class="msg-model">${meta.model.toUpperCase().slice(0,20)}</span>
      ${meta.ms ? `<span class="msg-ms">${meta.ms}ms</span>` : ''}
    </div>`;
  }
  el.innerHTML = `<div class="msg-who">${label}</div>
                  <div class="msg-txt">${clean}</div>
                  ${metaHtml}`;
  msgs.appendChild(el);
  msgs.scrollTop = msgs.scrollHeight;
}

let thinkEl = null;
function showThink() {
  const msgs = document.getElementById('msgs');
  thinkEl = document.createElement('div');
  thinkEl.className = 'think';
  thinkEl.innerHTML =
    '<div class="tdot"></div><div class="tdot"></div>' +
    '<div class="tdot"></div><span>FRIDAY IS THINKING...</span>';
  msgs.appendChild(thinkEl);
  msgs.scrollTop = msgs.scrollHeight;
}
function hideThink() {
  if (thinkEl) { thinkEl.remove(); thinkEl = null; }
}

function clearMsgs() {
  document.getElementById('msgs').innerHTML =
    '<div class="msg msg-sys"><div class="msg-who">SYSTEM</div>' +
    '<div class="msg-txt">Chat cleared.</div></div>';
}

function addAlert(text, type='i') {
  const al = document.getElementById('alerts');
  const nd = al.querySelector('.no-alerts');
  if (nd) nd.remove();
  const el = document.createElement('div');
  el.className = 'alert-item';
  el.innerHTML = `<div class="adot ${type}"></div>
                  <div class="alert-txt">${text.slice(0,100)}</div>`;
  al.prepend(el);
  while (al.children.length > 5) al.removeChild(al.lastChild);
}

function playAudio(file) {
  if (muted) return;
  if (currentAudio) { currentAudio.pause(); currentAudio=null; }
  const url = `${BASE}/friday/voice/audio?file=${file}&t=${Date.now()}`;
  currentAudio = new Audio(url);
  currentAudio.play().catch(()=>{});
}

function toggleMute() {
  muted = !muted;
  const b = document.getElementById('mute-btn');
  b.textContent = muted ? 'UNMUTE' : 'MUTE';
  b.className   = muted ? 'mute-btn on' : 'mute-btn';
  if (muted && currentAudio) currentAudio.pause();
}

function toggleMic() {
  recording = !recording;
  document.getElementById('mic-btn').className =
    recording ? 'mic-btn on' : 'mic-btn';
}

function toggleAmbient() {
  ambient = !ambient;
  document.getElementById('amb-btn').className =
    ambient ? 'ambient-btn on' : 'ambient-btn';
  if (ambient) startAmbient();
  else stopAmbient();
}

function startAmbient() {
  ambientCtx = new (window.AudioContext||window.webkitAudioContext)();
  const o1 = ambientCtx.createOscillator();
  const g1 = ambientCtx.createGain();
  o1.frequency.value = 55; o1.type = 'sine';
  g1.gain.value = 0.035;
  o1.connect(g1); g1.connect(ambientCtx.destination); o1.start();
  const o2 = ambientCtx.createOscillator();
  const g2 = ambientCtx.createGain();
  o2.frequency.value = 110; o2.type = 'sine';
  g2.gain.value = 0.015;
  o2.connect(g2); g2.connect(ambientCtx.destination); o2.start();
}

function stopAmbient() {
  if (ambientCtx) { ambientCtx.close(); ambientCtx=null; }
}

async function setVoiceMode(mode) {
  await fetch(`${BASE}/mode`, {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({mode}),
  });
}

async function pollState() {
  try {
    const r = await fetch(`${BASE}/state`);
    const d = await r.json();

    const dot = document.getElementById('s-dot');
    const txt = document.getElementById('s-txt');
    if (d.status === 'ONLINE') {
      dot.className = 's-dot';
      txt.textContent = 'FRIDAY ONLINE';
    } else {
      dot.className = 's-dot w';
      txt.textContent = d.status || 'DEGRADED';
    }

    const b = d.budget || {};
    const cpuTxt = (d.cpu_pct != null) ? `${Math.round(d.cpu_pct)}%` : '—';
    const ramTxt = (d.ram_pct != null) ? `${Math.round(d.ram_pct)}%` : '—';
    document.getElementById('h-cpu').textContent = cpuTxt;
    document.getElementById('h-ram').textContent = ramTxt;
    document.getElementById('cpu-v').textContent = cpuTxt;
    document.getElementById('ram-v').textContent = ramTxt;
    document.getElementById('cpu-b').style.width = (d.cpu_pct || 0) + '%';
    document.getElementById('ram-b').style.width = (d.ram_pct || 0) + '%';

    const up = d.uptime || 0;
    const h  = Math.floor(up/3600);
    const m  = Math.floor((up%3600)/60);
    const upStr = h ? `${h}h ${m}m` : `${m}m`;
    document.getElementById('h-up').textContent  = upStr;
    document.getElementById('up-v').textContent  = upStr;

    document.getElementById('h-jar').textContent =
      d.jarvis_online ? 'ONLINE' : 'OFFLINE';
    document.getElementById('j-status').textContent =
      d.jarvis_online ? '🟢 ONLINE' : '🔴 OFFLINE';
    document.getElementById('j-cover').textContent =
      d.coverage_mode ? '⚡ ACTIVE' : 'STANDBY';

    document.getElementById('cov-banner').className =
      d.coverage_mode ? 'cov-banner on' : 'cov-banner';

    document.getElementById('f-jarvis').className =
      d.jarvis_online ? 'f-dot g' : 'f-dot y';
    document.getElementById('f-cover').textContent =
      d.coverage_mode ? 'ACTIVE' : 'OFF';

    document.getElementById('api-v').textContent =
      `${b.calls||0}/${b.calls_limit||300}`;

    const trend = d.emotional_trend || {};
    if (Object.keys(trend).length) {
      document.getElementById('emotion-trend').innerHTML =
        Object.entries(trend)
          .sort((a,b)=>b[1]-a[1])
          .slice(0,4)
          .map(([e,c])=>`
            <div style="display:flex;justify-content:space-between;
              padding:3px 0;font-size:10px;
              border-top:1px solid rgba(0,255,128,0.04)">
              <span style="color:var(--muted)">${e}</span>
              <span style="color:var(--accent)">${c}</span>
            </div>`
          ).join('');
    }

    if (d.voice_mode) {
      document.getElementById('mode-badge').textContent =
        d.voice_mode.toUpperCase();
    }

    const sec = d.security || {};
    document.getElementById('st-threats').textContent =
      sec.threats || 0;
    document.getElementById('st-blocked').textContent =
      sec.blocked_ips || 0;
    const tNum = document.getElementById('threat-num');
    const threats = sec.threats || 0;
    tNum.textContent  = threats;
    tNum.className    = threats > 20 ? 'sentinel-num d' :
                        threats > 5  ? 'sentinel-num w' :
                        'sentinel-num';

  } catch(e) {
    document.getElementById('s-dot').className = 's-dot w';
  }
}

async function pollVeronica() {
  try {
    const r = await fetch(`${BASE}/friday/veronica/status`);
    const d = await r.json();
    const el = document.getElementById('ver-status');
    const backed = d.components_backed_up || 0;
    const repairs = d.repairs_performed || 0;
    el.innerHTML = `
      <div class="ver-item">
        <span class="stat-lbl">BACKED UP</span>
        <span class="ver-nominal">${backed} COMPONENTS</span>
      </div>
      <div class="ver-item">
        <span class="stat-lbl">REPAIRS</span>
        <span class="ver-nominal">${repairs}</span>
      </div>
      <div class="ver-item">
        <span class="stat-lbl">STATUS</span>
        <span class="ver-nominal">MONITORING</span>
      </div>`;
  } catch(e) {
    document.getElementById('ver-status').innerHTML =
      '<div style="font-size:10px;color:var(--muted);padding:8px 12px">Offline</div>';
  }
}

document.addEventListener('keydown', e => {
  if (e.ctrlKey && e.key==='/') {
    document.getElementById('inp').focus();
    e.preventDefault();
  }
});

pollState();
pollVeronica();
setInterval(pollState, 5000);
setInterval(pollVeronica, 30000);
document.getElementById('inp').focus();
</script>
</body>
</html>
"""

# ── Entry ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logging.info(f"FRIDAY V2 starting on port {port}")
    app.run(host="0.0.0.0", port=port)
