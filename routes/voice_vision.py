"""routes/voice_vision.py — Voice, vision, and calibration routes, split out of the former
monolithic server.py. Registered onto the main Flask app in server.py
via app.register_blueprint(voice_vision_bp); nothing here changes behavior,
only where the code lives.
"""
import os
import time
from flask import Blueprint, request, jsonify, send_file

from core.app_state import (
    BASE_DIR,
    HUD_OK,
    LOCKDOWN_TRIGGERS,
    TRANSCRIBE_OK,
    VOICE_OK,
    _log,
    calibration,
    drain_widgets,
    friday_speak,
    friday_vision,
    spawn_widget,
    transcribe_audio,
    voice_memory,
)

voice_vision_bp = Blueprint("voice_vision", __name__)


@voice_vision_bp.route("/friday/chat/upload", methods=["POST"])
def friday_chat_upload():
    """Multipart file (+ optional 'prompt' field) — a general chat
    attachment endpoint, not just images. FRIDAY had no way for an
    external client to hand her an arbitrary file at all before this
    (only /friday/vision/analyze, which is images-as-base64-JSON only).

    Saves the file, runs it through services/documents.py's ingest(), and
    folds the resulting summary into the prompt as a bracketed note
    before routing through /command exactly like any other message —
    same trick JARVIS_V5's core/attachments.py uses, so /command's ~1000
    lines of routing logic don't need to know attachments exist at all."""
    from werkzeug.utils import secure_filename

    if "file" not in request.files:
        return jsonify({"response": "No file attached, boss."}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"response": "Empty file, boss."}), 400

    upload_dir = BASE_DIR / "memory" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / f"{int(time.time())}_{secure_filename(f.filename)}"
    f.save(str(dest))

    from services import documents
    result = documents.ingest(str(dest))
    if not result.get("ok"):
        return jsonify({"response": f"Couldn't read that file, boss: {result.get('error', 'unknown error')}"}), 200

    note = f'[Attached file "{f.filename}": {result["summary"]}]'
    prompt = (request.form.get("prompt") or "").strip()
    combined_prompt = f"{prompt}\n\n{note}" if prompt else note

    # Lazy import -- server.py imports this module (to register the
    # blueprint) before server.app/server.command exist yet, so a
    # module-level `from server import app, command` would be circular.
    # By request-serving time (when this function actually runs), the
    # whole app has long since finished importing.
    import server
    with server.app.test_request_context("/command", method="POST", json={"prompt": combined_prompt}):
        return server.command()


@voice_vision_bp.route("/friday/vision/analyze", methods=["POST"])
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


@voice_vision_bp.route("/friday/vision/identify", methods=["POST"])
def friday_vision_identify():
    """HUD-style 'what am I looking at' — same base64 JSON input as
    /friday/vision/analyze, but a short spoken answer instead of an
    open-ended description, and it speaks the result (audio_file, same
    convention as /command's Mayday/normal replies) instead of leaving the
    caller to display text only."""
    if not friday_vision:
        return jsonify({"error": "Vision isn't available, boss."}), 503
    data = request.get_json(silent=True) or {}
    image_b64 = data.get("image", "")
    if not image_b64:
        return jsonify({"error": "No image provided."}), 400

    result = friday_vision.identify(image_b64)
    if "error" in result:
        _log("[image]", result["error"], "vision_identify")
        return jsonify(result)

    spoken = result["spoken"]
    audio_file = friday_speak(spoken) if VOICE_OK else None
    spawn_widget("text", {"title": result["label"] or "IDENTIFIED", "body": spoken}, audio_file)
    _log("[image]", spoken, "vision_identify")
    return jsonify({
        "label": result["label"], "spoken": spoken,
        "has_audio": bool(audio_file), "audio_file": audio_file,
    })


@voice_vision_bp.route("/friday/calibration/score")
def friday_calibration_score():
    if not calibration:
        return jsonify({"error": "Calibration tracking isn't available, boss."}), 503
    return jsonify(calibration.calibration_score())


@voice_vision_bp.route("/friday/calibration/resolve", methods=["POST"])
def friday_calibration_resolve():
    if not calibration:
        return jsonify({"error": "Calibration tracking isn't available, boss."}), 503
    data = request.get_json(silent=True) or {}
    pred_id = data.get("id", "")
    outcome = data.get("outcome")
    if not pred_id or outcome is None:
        return jsonify({"error": "id and outcome are required"}), 400
    return jsonify(calibration.resolve_prediction(pred_id, bool(outcome)))


@voice_vision_bp.route("/friday/voice/audio")
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


@voice_vision_bp.route("/friday/hud/poll")
def friday_hud_poll():
    """Polled every ~1s by the real /hud page's spawnWidget() system
    (static/js/hud.js). No WebSocket in this Flask
    process, so widgets sit in an in-memory queue until picked up here —
    see services/friday_hud.py. Delivered-once: each widget is returned
    exactly once, to whichever poll happens to catch it."""
    if not HUD_OK:
        return jsonify({"widgets": []})
    return jsonify({"widgets": drain_widgets()})


@voice_vision_bp.route("/friday/voice/transcribe", methods=["POST"])
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
    verify_result = None
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

    # Extra scrutiny for Suit Lockdown specifically: the general check
    # above only blocks a *confirmed* mismatch and fails open on anything
    # ambiguous (not enrolled, bridge unreachable, verify error) — the
    # right default for ordinary commands, but lockdown has no backdoor by
    # design, so a false trigger from ambient/background audio is a real
    # lockout, not just a wrong answer. Require a *positively confirmed*
    # match before a lockdown phrase is even allowed to reach command() as
    # text; anything less than that gets silently dropped here, same as a
    # confirmed mismatch — never even acknowledging the phrase was heard.
    # Typed lockdown triggers never pass through this route at all (no
    # audio involved) and are completely unaffected.
    text = (result.get("text") or "").lower()
    if any(t in text for t in LOCKDOWN_TRIGGERS):
        positively_verified = bool(verify_result) and verify_result.get("verified") is True and verify_result.get("match") is True
        if not positively_verified:
            return jsonify({"text": "", "rejected": True, "reason": "lockdown_requires_verified_speaker"})

    return jsonify(result)


@voice_vision_bp.route("/friday/voice/enroll", methods=["POST"])
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


@voice_vision_bp.route("/friday/voice/profile/status", methods=["GET"])
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


@voice_vision_bp.route("/friday/voice/reset", methods=["POST"])
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


@voice_vision_bp.route("/friday/voice/weekly")
def voice_weekly():
    if not voice_memory:
        return jsonify({"report": ""})
    return jsonify({"report": voice_memory.weekly_report()})
