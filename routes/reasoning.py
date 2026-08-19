"""routes/reasoning.py — Deep reasoning and OODA loop routes, split out of the former
monolithic server.py. Registered onto the main Flask app in server.py
via app.register_blueprint(reasoning_bp); nothing here changes behavior,
only where the code lives.
"""
from flask import Blueprint, request, jsonify

from core.app_state import (
    friday_brain,
)

reasoning_bp = Blueprint("reasoning", __name__)


@reasoning_bp.route("/friday/reason/deep", methods=["POST"])
def reason_deep():
    data = request.get_json(silent=True) or {}
    if not friday_brain:
        return jsonify({"error": "unavailable"}), 503
    return jsonify(friday_brain.deep_think(data.get("query", ""), data.get("context", "")))


@reasoning_bp.route("/friday/reason/critique", methods=["POST"])
def reason_critique():
    data = request.get_json(silent=True) or {}
    if not friday_brain:
        return jsonify({"error": "unavailable"}), 503
    improved = friday_brain.self_critique(data.get("query", ""), data.get("response", ""))
    return jsonify({"improved": improved})


@reasoning_bp.route("/friday/reason/parallel", methods=["POST"])
def reason_parallel():
    data = request.get_json(silent=True) or {}
    if not friday_brain:
        return jsonify({"error": "unavailable"}), 503
    return jsonify({"response": friday_brain.parallel_think(data.get("query", ""))})


@reasoning_bp.route("/friday/ooda", methods=["POST"])
def friday_ooda():
    data = request.get_json(silent=True) or {}
    from core.ooda import ooda
    return jsonify(ooda.run(data.get("situation", ""), data.get("context", "")))


@reasoning_bp.route("/friday/ooda/rapid", methods=["POST"])
def friday_ooda_rapid():
    data = request.get_json(silent=True) or {}
    from core.ooda import ooda
    return jsonify({"result": ooda.rapid_ooda(data.get("situation", ""))})
