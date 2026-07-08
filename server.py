"""FRIDAY V2 — complete server. Flask + emotional intelligence + JARVIS
monitoring + green HUD + voice-mode control."""
import os
import time
import datetime
import logging
import threading
from collections import deque
from pathlib import Path
from flask import Flask, request, jsonify, send_file

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)
BOOT_TIME = time.time()
EXCHANGE_LOG = deque(maxlen=10)
BASE_DIR = Path(__file__).resolve().parent

logging.basicConfig(level=logging.INFO, format='[FRIDAY] %(message)s')

# ── Core loading ─────────────────────────────────────────────────────────────
try:
    from core.friday_brain import friday_brain
    from core.emotional_intel import emotional_intel
    from core.friday_memory import (
        save_turn, get_recent_turns, get_context_for,
        save_fact, log_emotion, get_emotional_trend, get_profile,
        get_mood_history, friday_remember, friday_recall,
    )
    CORE_STATUS = "online"
    logging.info("Brain and emotional intelligence online")
except Exception as e:
    friday_brain = None
    emotional_intel = None
    CORE_STATUS = f"fallback ({e})"
    logging.warning(f"Core failed: {e}")

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


threading.Thread(target=_monitor_jarvis, daemon=True).start()

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


threading.Thread(target=_schedule_checkins, daemon=True).start()

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
    threading.Thread(target=_training_sync_loop, daemon=True).start()

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


def overall_status() -> str:
    if not friday_brain:
        return "EMERGENCY"
    brain_status = friday_brain.status()
    if not brain_status.get("groq") and not brain_status.get("anthropic"):
        return "NO-LLM"
    return "ONLINE"


# ── Health & status ───────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return "OK", 200


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

    return jsonify({
        "status": overall_status(), "core": CORE_STATUS,
        "jarvis_online": JARVIS_ONLINE, "coverage_mode": COVERAGE_MODE,
        "range_level": friday_protocols.range_level.value if PROTOCOLS_OK else "unknown",
        "training": friday_trainer.status() if TRAINING_OK else {},
        "budget": budget_info, "emotional_trend": emotional_trend,
        "uptime_seconds": int(time.time() - BOOT_TIME),
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

        # Dark mode — zero external connectivity, local-only responses
        if PROTOCOLS_OK and friday_protocols.range_level == RangeLevel.DARK:
            response = friday_protocols.emergency_response(prompt)
            _log(prompt, response, "emergency")
            return jsonify({"response": response, "mode": "emergency", "range": "dark"})

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
<title>FRIDAY · HUD</title>
<style>
:root {
  --bg:      #040d08;
  --panel:   rgba(0,255,128,0.03);
  --border:  rgba(0,255,128,0.15);
  --accent:  #00ff80;
  --accent2: #00ffcc;
  --warn:    #ffaa00;
  --danger:  #ff4444;
  --text:    #ccffe0;
  --muted:   #3a6650;
  --grid:    rgba(0,255,128,0.04);
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background:
    repeating-linear-gradient(0deg,var(--grid) 0,var(--grid) 1px,
    transparent 1px,transparent 4px), var(--bg);
  color: var(--text);
  font-family: 'Courier New', monospace;
  min-height: 100vh;
  padding: 20px;
}
.wrap { max-width: 900px; margin: 0 auto; }
header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--border);
  padding-bottom: 16px;
  margin-bottom: 20px;
  flex-wrap: wrap;
  gap: 10px;
}
.logo {
  font-size: 28px;
  font-weight: 900;
  letter-spacing: 10px;
  color: var(--accent);
  text-shadow: 0 0 20px rgba(0,255,128,0.4);
}
.logo-sub {
  font-size: 10px;
  letter-spacing: 3px;
  color: var(--muted);
  margin-top: 3px;
}
.status-area {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
}
.dot {
  display: inline-block;
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 8px var(--accent);
  animation: pulse 2.5s ease-in-out infinite;
}
.dot.warn   { background: var(--warn);   box-shadow: 0 0 8px var(--warn);   animation-duration: 1s; }
.dot.danger { background: var(--danger); box-shadow: 0 0 8px var(--danger); animation-duration: 0.5s; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
.status-pill {
  display: flex; align-items: center; gap: 8px;
  font-size: 12px; letter-spacing: 2px;
  color: var(--accent);
}
#clock { font-size: 11px; color: var(--muted); letter-spacing: 2px; }
main {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 16px;
}
@media(max-width:700px){ main { grid-template-columns: 1fr; } }
.panel {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 16px;
  position: relative;
}
.panel::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 1px;
  background: linear-gradient(90deg,transparent,var(--accent),transparent);
  opacity: 0.5;
}
.panel-title {
  font-size: 9px;
  letter-spacing: 4px;
  color: var(--muted);
  text-transform: uppercase;
  margin-bottom: 14px;
}
.stat-row {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  border-top: 1px solid rgba(0,255,128,0.06);
  font-size: 11px;
  color: var(--muted);
}
.stat-row span:last-child { color: var(--text); }
.emotion-badge {
  display: inline-block;
  padding: 3px 10px;
  border: 1px solid var(--border);
  border-radius: 2px;
  font-size: 10px;
  letter-spacing: 2px;
  color: var(--accent);
  margin-bottom: 10px;
}
.coverage-banner {
  background: rgba(255,170,0,0.08);
  border: 1px solid rgba(255,170,0,0.3);
  border-radius: 3px;
  padding: 8px 12px;
  font-size: 11px;
  letter-spacing: 1px;
  color: var(--warn);
  margin-bottom: 14px;
  display: none;
}
.coverage-banner.active { display: block; }
.chat-area {
  grid-column: 2;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.messages {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 14px;
  min-height: 300px;
  max-height: 400px;
  overflow-y: auto;
}
.msg { padding: 8px 0; border-top: 1px solid rgba(0,255,128,0.06); }
.msg:first-child { border-top: none; }
.msg-label { font-size: 9px; letter-spacing: 3px; color: var(--muted); margin-bottom: 4px; }
.msg-user .msg-label { color: var(--accent2); }
.msg-friday .msg-label { color: var(--accent); }
.msg-system { color: var(--muted); font-size: 11px; text-align: center; padding: 8px 0; }
.msg-text { font-size: 13px; line-height: 1.6; }
.msg-user .msg-text { color: var(--accent2); }
.input-row {
  display: flex;
  gap: 8px;
}
.chat-input {
  flex: 1;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 3px;
  color: var(--text);
  padding: 10px 14px;
  font-family: inherit;
  font-size: 13px;
  outline: none;
}
.chat-input:focus { border-color: var(--accent); }
.chat-input::placeholder { color: var(--muted); }
.btn {
  background: transparent;
  border: 1px solid var(--accent);
  color: var(--accent);
  padding: 10px 16px;
  border-radius: 3px;
  cursor: pointer;
  font-family: inherit;
  font-size: 11px;
  letter-spacing: 2px;
}
.btn:hover { background: rgba(0,255,128,0.08); }
.log-area {
  grid-column: 1 / -1;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 14px;
  max-height: 180px;
  overflow-y: auto;
}
.log-entry {
  display: flex;
  gap: 12px;
  padding: 6px 0;
  border-top: 1px solid rgba(0,255,128,0.05);
  font-size: 11px;
}
.log-entry:first-child { border-top: none; }
.log-ts { color: var(--muted); white-space: nowrap; }
.log-mode { padding: 1px 6px; border: 1px solid var(--border); border-radius: 2px; font-size: 9px; letter-spacing: 1px; }
.log-mode.friday { color: var(--accent); }
.log-mode.jarvis { color: #00b4ff; }
.log-mode.coverage { color: var(--warn); }
.log-mode.emergency { color: var(--danger); }
.log-text { color: var(--text); flex: 1; }
footer { margin-top: 14px; text-align: center; font-size: 9px; letter-spacing: 3px; color: var(--muted); }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <div class="logo">FRIDAY</div>
      <div class="logo-sub">FEMALE REPLACEMENT INTELLIGENT DIGITAL ASSISTANT YOUTH · V2.0</div>
    </div>
    <div class="status-area">
      <div class="status-pill">
        <span class="dot" id="status-dot"></span>
        <span id="status-text">CONNECTING</span>
      </div>
      <div id="clock">--:--:--</div>
    </div>
  </header>

  <main>
    <!-- Left: Stats -->
    <div class="panel">
      <div class="panel-title">SYSTEM STATUS</div>
      <div class="coverage-banner" id="coverage-banner">
        ⚡ COVERAGE MODE — JARVIS OFFLINE
      </div>
      <div class="emotion-badge" id="emotion-badge">NEUTRAL</div>
      <div class="stat-row"><span>JARVIS</span><span id="jarvis-status">—</span></div>
      <div class="stat-row"><span>BRAIN</span><span id="brain-status">—</span></div>
      <div class="stat-row"><span>VOICE MODE</span><span id="voice-mode">—</span></div>
      <div class="stat-row"><span>UPTIME</span><span id="uptime">—</span></div>
      <div class="stat-row"><span>API CALLS</span><span id="api-calls">—</span></div>
      <div class="stat-row"><span>TOKENS</span><span id="api-tokens">—</span></div>
      <div style="margin-top:14px">
        <div class="panel-title">EMOTIONAL TREND</div>
        <div id="emotion-trend" style="font-size:11px;color:var(--muted)">No data yet</div>
      </div>
      <div style="margin-top:14px;display:flex;gap:6px;flex-wrap:wrap">
        <button class="btn" style="padding:5px 10px;font-size:9px" onclick="setMode('normal')">NORMAL</button>
        <button class="btn" style="padding:5px 10px;font-size:9px" onclick="setMode('focused')">FOCUSED</button>
        <button class="btn" style="padding:5px 10px;font-size:9px" onclick="setMode('brief')">BRIEF</button>
      </div>
    </div>

    <!-- Right: Chat -->
    <div class="chat-area">
      <div class="messages" id="messages">
        <div class="msg-system">FRIDAY V2 — Say something, boss.</div>
      </div>
      <div class="input-row">
        <input class="chat-input" id="input"
               placeholder="Talk to FRIDAY..."
               onkeydown="if(event.key==='Enter'){send()}">
        <button class="btn" onclick="send()">SEND</button>
      </div>
    </div>

    <!-- Exchange log -->
    <div class="log-area">
      <div class="panel-title">EXCHANGE LOG</div>
      <div id="log"></div>
    </div>
  </main>

  <footer>FRIDAY V2 · AUTO-REFRESH 5S</footer>
</div>

<script>
// Same origin as the page that served this HUD — no hardcoded port. Avoids
// the class of bug JARVIS's mobile HUD had (forcing a fixed port regardless
// of what's actually serving the page breaks it behind any proxy/CDN).
const BASE = `${location.protocol}//${location.host}`;

function tick() {
  document.getElementById('clock').textContent =
    new Date().toLocaleTimeString([], {hour12:false});
}
setInterval(tick, 1000); tick();

async function send() {
  const inp  = document.getElementById('input');
  const text = inp.value.trim();
  if (!text) return;
  inp.value = '';
  addMsg('user', 'YOU', text);

  try {
    const r = await fetch(`${BASE}/command`, {
      method:  'POST',
      headers: {'Content-Type': 'application/json'},
      body:    JSON.stringify({prompt: text}),
    });
    const d = await r.json();
    addMsg('friday', 'FRIDAY', d.response || '...');
    if (d.has_audio && d.audio_file) {
      playAudio(d.audio_file);
    }
  } catch(e) {
    addMsg('friday', 'FRIDAY', 'Connection issue, boss.');
  }
}

let _currentAudio = null;
function playAudio(file) {
  if (_currentAudio) { _currentAudio.pause(); _currentAudio = null; }
  _currentAudio = new Audio(`${BASE}/friday/voice/audio?file=${encodeURIComponent(file)}&t=${Date.now()}`);
  _currentAudio.play().catch(e => console.log('Audio:', e));
}

function addMsg(type, label, text) {
  const m  = document.getElementById('messages');
  const el = document.createElement('div');
  el.className = `msg msg-${type}`;
  el.innerHTML = `<div class="msg-label">${label}</div>
                  <div class="msg-text">${text}</div>`;
  m.appendChild(el);
  m.scrollTop = m.scrollHeight;
}

async function poll() {
  try {
    const r = await fetch(`${BASE}/state`);
    const d = await r.json();

    const online = d.status === 'ONLINE';
    document.getElementById('status-dot').className =
      'dot' + (online ? '' : ' warn');
    document.getElementById('status-text').textContent =
      d.status || 'UNKNOWN';

    document.getElementById('jarvis-status').textContent =
      d.jarvis_online ? '🟢 ONLINE' : '🔴 OFFLINE';
    document.getElementById('brain-status').textContent =
      d.core || '—';
    document.getElementById('voice-mode').textContent =
      (d.voice_mode || 'normal').toUpperCase();

    const up = d.uptime_seconds || 0;
    const h  = Math.floor(up/3600);
    const m  = Math.floor((up%3600)/60);
    document.getElementById('uptime').textContent =
      h ? `${h}h ${m}m` : `${m}m`;

    const b = d.budget || {};
    document.getElementById('api-calls').textContent =
      `${b.calls||0} / ${b.calls_limit||150}`;
    document.getElementById('api-tokens').textContent =
      `${(b.output_tokens||0).toLocaleString()} / ${(b.output_tokens_limit||30000).toLocaleString()}`;

    const banner = document.getElementById('coverage-banner');
    banner.className = 'coverage-banner' + (d.coverage_mode ? ' active' : '');

    const trend = d.emotional_trend || {};
    const trendEl = document.getElementById('emotion-trend');
    if (Object.keys(trend).length) {
      trendEl.textContent = Object.entries(trend)
        .sort((a,b)=>b[1]-a[1])
        .slice(0,3)
        .map(([e,c])=>`${e}: ${c}`)
        .join(' · ');
    }

    const log    = d.log || [];
    const logEl  = document.getElementById('log');
    logEl.innerHTML = '';
    log.forEach(e => {
      const el   = document.createElement('div');
      el.className = 'log-entry';
      el.innerHTML = `
        <span class="log-ts">${e.ts}</span>
        <span class="log-mode ${e.mode}">${e.mode}</span>
        <span class="log-text">${e.user?.slice(0,60)} → ${e.response?.slice(0,80)}</span>
      `;
      logEl.appendChild(el);
    });

  } catch(e) {
    document.getElementById('status-dot').className = 'dot danger';
    document.getElementById('status-text').textContent = 'UNREACHABLE';
  }
}

async function setMode(mode) {
  await fetch(`${BASE}/mode`, {
    method:  'POST',
    headers: {'Content-Type': 'application/json'},
    body:    JSON.stringify({mode}),
  });
}

poll();
setInterval(poll, 5000);
</script>
</body>
</html>
"""

# ── Entry ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logging.info(f"FRIDAY V2 starting on port {port}")
    app.run(host="0.0.0.0", port=port)
