"""routes/goals.py — Goal tracking routes, split out of the former
monolithic server.py. Registered onto the main Flask app in server.py
via app.register_blueprint(goals_bp); nothing here changes behavior,
only where the code lives.
"""
from flask import Blueprint, request, jsonify

from core.app_state import (
    goals,
)

goals_bp = Blueprint("goals", __name__)


@goals_bp.route("/friday/goals")
def get_goals():
    if not goals:
        return jsonify([])
    return jsonify(goals.get_active_goals())


@goals_bp.route("/friday/goals/add", methods=["POST"])
def add_goal():
    data = request.get_json(silent=True) or {}
    if not goals:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(goals.add_goal(
        data.get("name", ""), data.get("description", ""),
        data.get("target_date", ""), data.get("milestones", []),
    ))


@goals_bp.route("/friday/goals/progress", methods=["POST"])
def log_goal_progress():
    data = request.get_json(silent=True) or {}
    if not goals:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(goals.log_progress(
        data.get("goal_id", ""), data.get("work", ""), auto_detect=True,
    ))


@goals_bp.route("/friday/goals/report")
def goal_report():
    if not goals:
        return jsonify({"report": ""})
    return jsonify({"report": goals.weekly_progress_report()})
