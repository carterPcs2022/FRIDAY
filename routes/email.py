"""routes/email.py — Email (Gmail read/draft/send) routes, split out of the former
monolithic server.py. Registered onto the main Flask app in server.py
via app.register_blueprint(email_bp); nothing here changes behavior,
only where the code lives.
"""
from flask import Blueprint, request, jsonify, redirect

from core.app_state import (
    friday_gmail,
)
from core.verification_engine import verify_email_sent

email_bp = Blueprint("email", __name__)


@email_bp.route("/friday/gmail/auth")
def gmail_send_auth():
    """One-time OAuth2 setup for *sending* mail via the Gmail API (see
    services/friday_gmail.py's module docstring for why sending moved off
    raw SMTP). Same shape as /friday/calendar/auth — not in
    core/access_auth.py's EXEMPT_PATHS, same as that route: reaching this
    at all already requires the boss's own logged-in session, and the
    Google redirect back to the callback below rides that same
    same-origin cookie."""
    if not friday_gmail or not friday_gmail.send_is_configured():
        return "Gmail sending not configured", 500
    return redirect(friday_gmail.send_auth_url())


@email_bp.route("/friday/gmail/callback")
def gmail_send_callback():
    if not friday_gmail:
        return "Gmail sending not configured", 500
    code = request.args.get("code", "")
    if not code:
        return jsonify({"error": request.args.get("error", "No code provided")}), 400
    result = friday_gmail.send_exchange_code(code)
    if result.get("ok"):
        return "Gmail sending connected. You can close this tab, boss."
    return jsonify(result), 400


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
    # Both fields present -> a fully-specified new email, sent directly.
    # Anything less (neither, or just one) -> send_draft(), which fills in
    # whatever's missing from the pending draft -- that's what lets a
    # caller redirect ("to" only) or tweak ("body" only) the draft without
    # re-specifying the whole thing. `to or body` here would wrongly send
    # a partial override straight to send_email(), which then fails on
    # the half that was never supplied instead of falling back to the draft.
    if to and body:
        result = friday_gmail.send_email(
            to=to, subject=subject, body=body,
            in_reply_to=data.get("in_reply_to", ""), attachments=attachments,
        )
    else:
        result = friday_gmail.send_draft(to=to, body=body, attachments=attachments)
    # V3 Phase 13: send_email()'s own {"ok": ...} is already the only
    # signal plain SMTP offers -- standardize it rather than invent
    # depth that isn't there (see core/verification_engine.py).
    result["verification"] = verify_email_sent(result).to_dict()
    return jsonify(result), (200 if result.get("ok") else 400)
