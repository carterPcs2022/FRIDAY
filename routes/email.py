"""routes/email.py — Email (Gmail read/draft/send) routes, split out of the former
monolithic server.py. Registered onto the main Flask app in server.py
via app.register_blueprint(email_bp); nothing here changes behavior,
only where the code lives.
"""
from flask import Blueprint, request, jsonify

from core.app_state import (
    friday_gmail,
)

email_bp = Blueprint("email", __name__)


@email_bp.route("/friday/email/summary")
def email_summary():
    if not friday_gmail:
        return jsonify({"summary": "Gmail not configured"})
    return jsonify({"summary": friday_gmail.summarize_inbox()})


@email_bp.route("/friday/email/urgent")
def email_urgent():
    if not friday_gmail:
        return jsonify({"urgent": []})
    return jsonify({"urgent": friday_gmail.get_urgent()})


@email_bp.route("/friday/email/draft", methods=["POST"])
def email_draft():
    data = request.get_json(silent=True) or {}
    if not friday_gmail:
        return jsonify({"error": "Gmail not configured"}), 503
    return jsonify(friday_gmail.draft_reply(
        email_subject=data.get("subject", ""), email_from=data.get("from", ""),
        email_body=data.get("body", ""), instruction=data.get("instruction", ""),
        message_id=data.get("message_id", ""),
    ))


@email_bp.route("/friday/email/triage")
def email_triage():
    if not friday_gmail:
        return jsonify({"error": "Gmail not configured"}), 503
    return jsonify(friday_gmail.smart_triage())


@email_bp.route("/friday/email/send", methods=["POST"])
def email_send():
    """Sends directly when to/body are given; sends the last draft_reply()
    output otherwise. Same auth gate as every other data route (see
    core/access_auth.py) — this isn't exempt, and it's the one email route
    that actually puts a message in someone's inbox."""
    data = request.get_json(silent=True) or {}
    if not friday_gmail:
        return jsonify({"error": "Gmail not configured"}), 503
    to = data.get("to", "")
    subject = data.get("subject", "")
    body = data.get("body", "")
    attachments = data.get("attachments") or None
    if to or body:
        result = friday_gmail.send_email(
            to=to, subject=subject, body=body,
            in_reply_to=data.get("in_reply_to", ""), attachments=attachments,
        )
    else:
        result = friday_gmail.send_draft(to=to, body=body, attachments=attachments)
    return jsonify(result), (200 if result.get("ok") else 400)
