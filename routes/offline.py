"""routes/offline.py — offline mode: serving the service worker from
root scope, telling the client where to find the local model (if
configured), and a single aggregated read-only snapshot for the
client to cache while online and show while offline.

Offline mode itself lives almost entirely in the browser
(static/js/offline_model.js, offline_sync.js, service-worker.js) --
this file is the small server-side surface it needs: the service
worker MUST be served from "/" (not "/static/js/...") for its default
scope to cover the whole origin, including page navigations to /hud,
which is why it gets a dedicated route instead of just living in
static/ like the rest of the frontend assets.
"""
import os
from pathlib import Path
from flask import Blueprint, Response, jsonify

from core.app_state import BASE_DIR, friday_calendar, get_tasks

offline_bp = Blueprint("offline", __name__)

# Set by the boss once they've exported+hosted their fine-tuned GGUF
# somewhere the browser can fetch it directly (e.g. a Hugging Face
# model repo) -- see the offline-mode scoping conversation for why this
# can't be bundled into the repo or served off Render itself (multi-GB
# file, way past what a free/starter web service should be hosting).
OFFLINE_MODEL_URL = os.getenv("FRIDAY_OFFLINE_MODEL_URL", "")

# Matches the system prompt the model was actually fine-tuned on
# (see friday_training_data.jsonl) rather than the full production
# FRIDAY_PERSONALITY -- a 3B model run in a browser tab does best with
# the exact framing it saw during training, not a ~1400-token prompt
# competing with its 2048-token context window for room to answer in.
OFFLINE_SYSTEM_PROMPT = (
    "You are FRIDAY, Tony Stark's autonomous Irish-accented AI assistant. "
    "You are currently running fully offline, locally on the boss's device, "
    "with no access to email, calendar, tasks, smart home, or any other "
    "real system -- only this conversation. Don't claim to have sent, "
    "checked, or changed anything real."
)


@offline_bp.route("/service-worker.js")
def service_worker():
    path = BASE_DIR / "static" / "js" / "service-worker.js"
    return Response(path.read_text(), mimetype="application/javascript",
                     headers={"Service-Worker-Allowed": "/"})


@offline_bp.route("/friday/offline/config")
def offline_config():
    return jsonify({
        "enabled": bool(OFFLINE_MODEL_URL),
        "model_url": OFFLINE_MODEL_URL,
        "system_prompt": OFFLINE_SYSTEM_PROMPT,
    })


@offline_bp.route("/friday/offline/snapshot")
def offline_snapshot():
    """One aggregated, read-only fetch for everything offline mode's
    cached-data panel shows -- tasks, notes, upcoming calendar -- so the
    client does one round trip and one cache write instead of three."""
    from core.friday_memory import get_notes

    events = friday_calendar.get_upcoming(48) if friday_calendar else []
    return jsonify({
        "tasks": get_tasks(),
        "notes": get_notes(),
        "events": events,
        "synced_at": None,  # filled in client-side with the fetch time
    })
