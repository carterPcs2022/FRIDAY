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

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(f) for f in (_news, _people, _brain)]
        concurrent.futures.wait(futures, timeout=25)

    combined = "\n".join(f"- {v}" for v in parts.values() if v)
    if not combined:
        return ""
    if not friday_brain:
        return combined

    result = friday_brain.think(
        f"Combine these into one morning brief for the boss:\n{combined}\n\n"
        f"News, relationships needing attention, and anything relevant from "
        f"stored knowledge. One flowing brief, not separate sections. "
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

</style>
</head>
<body>

<div class="particles" id="particles"></div>
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
      <div class="logo-orb"></div>
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
      <input class="chat-inp" id="chat-inp" placeholder="Talk to FRIDAY, boss..."
             onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();send()}">
      <button class="mic-btn" id="mic-btn" onclick="toggleMic()">&#127908;</button>
      <button class="send-btn" onclick="send()">&#9654;</button>
    </div>
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
    .replace(/\[Confidence:\s*\d+%\]/gi, '')
    .replace(/_FYI:.*?_/gi, '')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>');
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
  currentAudio.play().catch(() => {});
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

pollState();
pollVeronica();
setInterval(pollState, 5000);
setInterval(pollVeronica, 30000);
document.getElementById('chat-inp').focus();

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeAll();
  if (e.ctrlKey && e.key === '/') { document.getElementById('chat-inp').focus(); e.preventDefault(); }
});
</script>
</body>
</html>
"""

# ── Entry ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logging.info(f"FRIDAY V2 starting on port {port}")
    app.run(host="0.0.0.0", port=port)
