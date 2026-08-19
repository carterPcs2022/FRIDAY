"""routes/health_medicine.py — Health logging and medicine tracking routes, split out of the former
monolithic server.py. Registered onto the main Flask app in server.py
via app.register_blueprint(health_medicine_bp); nothing here changes behavior,
only where the code lives.
"""
import time
from flask import Blueprint, request, jsonify

from core.app_state import (
    HEALTH_OK,
    friday_health,
    medicine_tracker,
)

health_medicine_bp = Blueprint("health_medicine", __name__)


@health_medicine_bp.route("/friday/health/log", methods=["POST"])
def health_log():
    if not HEALTH_OK:
        return jsonify({"error": "health monitor unavailable"}), 503
    data = request.get_json(silent=True) or {}
    entry = friday_health.log_from_watch(
        heart_rate=data.get("heart_rate", 0), hrv=data.get("hrv", 0),
        blood_oxygen=data.get("blood_oxygen", 0), steps=data.get("steps", 0),
        sleep_hours=data.get("sleep_hours", 0), sleep_quality=data.get("sleep_quality", 0),
    )
    return jsonify(entry)


@health_medicine_bp.route("/friday/medicine/add", methods=["POST"])
def medicine_add():
    if not medicine_tracker:
        return jsonify({"error": "unavailable"}), 503
    data = request.get_json(silent=True) or {}
    return jsonify(medicine_tracker.add_medicine(
        data.get("name", ""), data.get("times", []),
        data.get("dosage", ""), data.get("notes", "")
    ))


@health_medicine_bp.route("/friday/medicine/list")
def medicine_list():
    if not medicine_tracker:
        return jsonify([])
    return jsonify(medicine_tracker.get_active_medicines())


@health_medicine_bp.route("/friday/medicine/taken", methods=["POST"])
def medicine_taken():
    if not medicine_tracker:
        return jsonify({"error": "unavailable"}), 503
    data = request.get_json(silent=True) or {}
    return jsonify(medicine_tracker.log_taken(data.get("name", "")))


@health_medicine_bp.route("/friday/medicine/due")
def medicine_due():
    if not medicine_tracker:
        return jsonify([])
    return jsonify(medicine_tracker.get_due_now())


@health_medicine_bp.route("/friday/hud/medicine")
def hud_medicine_display():
    """
    Minimal JSON designed for a microcontroller/HUD display
    to poll directly — small payload, no auth complexity,
    designed for a battery-powered device polling every
    30-60 seconds.
    """
    if not medicine_tracker:
        return jsonify({"due": [], "missed": []})
    return jsonify({
        "due": medicine_tracker.get_due_now(window_minutes=10),
        "missed": medicine_tracker.get_missed_today(),
        "ts": time.time(),
    })
