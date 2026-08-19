"""routes/habits_journal.py — Habits, journal, focus sessions routes, split out of the former
monolithic server.py. Registered onto the main Flask app in server.py
via app.register_blueprint(habits_journal_bp); nothing here changes behavior,
only where the code lives.
"""
from flask import Blueprint, request, jsonify

from core.app_state import (
    _FOCUS_SESSION,
    habits,
    journal,
)

habits_journal_bp = Blueprint("habits_journal", __name__)


@habits_journal_bp.route("/friday/habits")
def get_habits():
    if not habits:
        return jsonify({})
    return jsonify(habits.all_streaks())


@habits_journal_bp.route("/friday/habits/log", methods=["POST"])
def log_habit():
    data = request.get_json(silent=True) or {}
    name = data.get("habit", "").strip()
    if not name or not habits:
        return jsonify({"error": "No habit"}), 400
    return jsonify(habits.log(name))


@habits_journal_bp.route("/friday/journal/log", methods=["POST"])
def journal_log():
    data = request.get_json(silent=True) or {}
    content = data.get("content", "").strip()
    if not content or not journal:
        return jsonify({"error": "No content"}), 400
    return jsonify(journal.log_entry(content))


@habits_journal_bp.route("/friday/journal")
def friday_journal():
    if not journal:
        return jsonify({"entries": []})
    return jsonify({"entries": journal.recent_entries(365)})


@habits_journal_bp.route("/friday/journal/reflection")
def journal_reflection():
    if not journal:
        return jsonify({"reflection": ""})
    return jsonify({"reflection": journal.weekly_reflection()})


@habits_journal_bp.route("/friday/focus/status")
def focus_status():
    return jsonify(_FOCUS_SESSION)
