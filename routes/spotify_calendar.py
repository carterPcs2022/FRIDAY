"""routes/spotify_calendar.py — Spotify and Google Calendar OAuth routes, split out of the former
monolithic server.py. Registered onto the main Flask app in server.py
via app.register_blueprint(spotify_calendar_bp); nothing here changes behavior,
only where the code lives.
"""
from flask import Blueprint, request, jsonify, redirect

from core.app_state import (
    friday_calendar,
    friday_google_calendar,
    friday_spotify,
)

spotify_calendar_bp = Blueprint("spotify_calendar", __name__)


@spotify_calendar_bp.route("/friday/spotify/auth")
def spotify_auth():
    if not friday_spotify:
        return "Spotify not configured", 500
    return redirect(friday_spotify.auth_url())


@spotify_calendar_bp.route("/friday/spotify/callback")
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


# The /auth + /callback endpoints are the Google OAuth flow specifically,
# so they target the Google instance regardless of which backend is
# active. Apple needs no browser flow -- it's configured with an
# app-specific password via env vars (see services/friday_apple_calendar.py).
@spotify_calendar_bp.route("/friday/calendar/auth")
def calendar_auth():
    if not friday_google_calendar or not friday_google_calendar.is_configured():
        return "Google Calendar not configured", 500
    return redirect(friday_google_calendar.auth_url())


@spotify_calendar_bp.route("/friday/calendar/callback")
def calendar_callback():
    if not friday_google_calendar:
        return "Google Calendar not configured", 500
    code = request.args.get("code", "")
    if not code:
        return jsonify({"error": request.args.get("error", "No code provided")}), 400
    result = friday_google_calendar.exchange_code(code)
    if result.get("ok"):
        return "Calendar connected. You can close this tab, boss."
    return jsonify(result), 400


@spotify_calendar_bp.route("/friday/calendar/today")
def calendar_today():
    if not friday_calendar:
        return jsonify({"events": []})
    return jsonify({"events": friday_calendar.get_today()})


@spotify_calendar_bp.route("/friday/calendar/upcoming")
def calendar_upcoming():
    if not friday_calendar:
        return jsonify({"events": []})
    hours = request.args.get("hours", 24, type=int)
    return jsonify({"events": friday_calendar.get_upcoming(hours)})
