"""routes/tasks_workouts.py — Notes, tasks, workouts, bills, call log routes, split out of the former
monolithic server.py. Registered onto the main Flask app in server.py
via app.register_blueprint(tasks_workouts_bp); nothing here changes behavior,
only where the code lives.
"""
import datetime
from flask import Blueprint, request, jsonify

from core.app_state import (
    add_task,
    complete_task,
    friday_brain,
    get_tasks,
    get_workouts,
    log_workout,
    relationships,
)

tasks_workouts_bp = Blueprint("tasks_workouts", __name__)


@tasks_workouts_bp.route("/friday/notes")
def friday_notes():
    from core.friday_memory import get_notes
    return jsonify({"notes": get_notes()})


@tasks_workouts_bp.route("/friday/tasks")
def friday_tasks():
    return jsonify({"tasks": get_tasks()})


@tasks_workouts_bp.route("/friday/tasks/add", methods=["POST"])
def friday_tasks_add():
    data = request.get_json(silent=True) or {}
    task = data.get("task", "").strip()
    if not task:
        return jsonify({"error": "task required"}), 400
    return jsonify(add_task(task, data.get("priority", "normal")))


@tasks_workouts_bp.route("/friday/tasks/complete", methods=["POST"])
def friday_tasks_complete():
    data = request.get_json(silent=True) or {}
    task_id = data.get("id")
    if task_id is None:
        return jsonify({"error": "id required"}), 400
    complete_task(int(task_id))
    return jsonify({"completed": True, "id": task_id})


@tasks_workouts_bp.route("/friday/workout/log", methods=["POST"])
def workout_log():
    data = request.get_json(silent=True) or {}
    log_workout(data.get("type", "workout"), data.get("duration", 0))
    return jsonify({"logged": True})


@tasks_workouts_bp.route("/friday/workout/streak")
def workout_streak():
    workouts = get_workouts()
    if not workouts:
        return jsonify({"streak": 0})

    dates = sorted(set(w["ts"][:10] for w in workouts), reverse=True)
    streak = 0
    expected = datetime.datetime.now().date()
    for date_str in dates:
        date = datetime.datetime.fromisoformat(date_str).date()
        if date >= expected - datetime.timedelta(days=1):
            streak += 1
            expected = date - datetime.timedelta(days=1)
        else:
            break
    return jsonify({"streak": streak, "dates": dates[:7]})


@tasks_workouts_bp.route("/friday/bills/add", methods=["POST"])
def add_bill():
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    from core.friday_bills import add_bill as _add_bill
    _add_bill(name, data.get("amount", 0), data.get("due_day", 1))
    return jsonify({"added": True})


@tasks_workouts_bp.route("/friday/call/log", methods=["POST"])
def log_call():
    """Called after a call ends via iOS Shortcut."""
    data = request.get_json(silent=True) or {}
    contact = data.get("contact", "")
    duration = data.get("duration", 0)
    notes = data.get("notes", "")

    if contact and relationships:
        relationships.log_contact(contact, notes=f"Call ({duration} min): {notes}")

    response = f"Call with {contact} logged, boss." if contact else "Call logged, boss."
    if friday_brain:
        result = friday_brain.think(
            f"Call ended with {contact}. Duration: {duration} minutes. Notes: {notes}\n\n"
            f"Brief acknowledgment. Under 10 words."
        )
        response = result["response"] or response

    return jsonify({"response": response, "logged": True})
