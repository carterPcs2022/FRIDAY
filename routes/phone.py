"""routes/phone.py — Phone (Twilio + Pushcut) routes, split out of the former
monolithic server.py. Registered onto the main Flask app in server.py
via app.register_blueprint(phone_bp); nothing here changes behavior,
only where the code lives.
"""
import os
from flask import Blueprint, request, jsonify, Response

from core.app_state import (
    SECURITY_OK,
    friday_security,
)

phone_bp = Blueprint("phone", __name__)


@phone_bp.route("/friday/phone/call", methods=["POST"])
def friday_phone_call():
    from services.friday_phone import friday_phone
    return Response(friday_phone.handle_incoming_call(), mimetype="text/xml")


@phone_bp.route("/friday/phone/respond", methods=["POST"])
def friday_phone_respond():
    from services.friday_phone import friday_phone
    transcript = request.form.get("TranscriptionText") or "Hey"
    return Response(friday_phone.handle_response(transcript), mimetype="text/xml")


@phone_bp.route("/friday/phone/transcribed", methods=["POST"])
def friday_phone_transcribed():
    """Twilio's async transcription callback — nothing to do, /respond
    already handled the turn with its own (faster) transcription."""
    return Response("", mimetype="text/xml")


@phone_bp.route("/friday/phone/sms", methods=["POST"])
def friday_phone_sms():
    from services.friday_phone import friday_phone
    friday_phone.handle_sms(request.form.get("From", ""), request.form.get("Body", ""))
    return Response("<Response/>", mimetype="text/xml")


@phone_bp.route("/friday/phone/alert", methods=["POST"])
def friday_phone_alert():
    """Have FRIDAY place a real call and speak a message — 'call me and
    tell me Y', not a webhook. Same friday_security.screen_request() IP
    screening as /command, since this triggers a real outbound Twilio call
    (billable, and reaches a real phone) rather than just returning data."""
    from services.friday_phone import friday_phone
    if SECURITY_OK:
        screen = friday_security.screen_request(friday_security.client_ip(request), "phone alert")
        if screen.get("blocked"):
            return jsonify({"error": "Request blocked"}), 403
    data = request.get_json(silent=True) or {}
    to_number = data.get("to") or os.environ.get("MY_PHONE_NUMBER", "")
    message = data.get("message", "")
    if not to_number or not message:
        return jsonify({"error": "Both 'to' and 'message' are required"}), 400
    return jsonify(friday_phone.send_alert_call(message, to_number))


@phone_bp.route("/friday/phone/text", methods=["POST"])
def friday_phone_text():
    """FRIDAY sends a real text, not a webhook reply — 'text me Y' or
    'text [contact] Y'. Same billable-action IP screening as /phone/alert;
    an outbound SMS costs real money same as a real call."""
    from services.friday_phone import friday_phone
    if SECURITY_OK:
        screen = friday_security.screen_request(friday_security.client_ip(request), "phone text")
        if screen.get("blocked"):
            return jsonify({"error": "Request blocked"}), 403
    data = request.get_json(silent=True) or {}
    to_number = data.get("to") or os.environ.get("MY_PHONE_NUMBER", "")
    message = data.get("message", "")
    if not to_number or not message:
        return jsonify({"error": "Both 'to' and 'message' are required"}), 400
    return jsonify(friday_phone.send_sms(to_number, message))


@phone_bp.route("/friday/phone/call-from-device", methods=["POST"])
def friday_pushcut_call():
    from services.friday_pushcut import call as pushcut_call, is_configured
    if not is_configured():
        return jsonify({"error": "Pushcut not configured (PUSHCUT_API_KEY missing)"}), 503
    if SECURITY_OK:
        screen = friday_security.screen_request(friday_security.client_ip(request), "pushcut call")
        if screen.get("blocked"):
            return jsonify({"error": "Request blocked"}), 403
    data = request.get_json(silent=True) or {}
    target = data.get("to", "")
    if not target:
        return jsonify({"error": "'to' (a phone number or contact name) is required"}), 400
    result = pushcut_call(target)
    if not result.get("ok"):
        return jsonify(result), 502
    return jsonify(result)


@phone_bp.route("/friday/phone/call-mom", methods=["POST"])
def friday_pushcut_call_mom():
    """Free-tier stopgap until Pushcut Pro/Plus is active — see
    services/friday_pushcut.py's module docstring. Fixed target, no body
    needed; fires a static notification that still needs a tap on his
    phone to actually place the call."""
    from services.friday_pushcut import call_mom
    if SECURITY_OK:
        screen = friday_security.screen_request(friday_security.client_ip(request), "pushcut call mom")
        if screen.get("blocked"):
            return jsonify({"error": "Request blocked"}), 403
    result = call_mom()
    if not result.get("ok"):
        return jsonify(result), 502
    return jsonify(result)
