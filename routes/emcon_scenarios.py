"""routes/emcon_scenarios.py — EMCON, scenario planning, Sokovia framework routes, split out of the former
monolithic server.py. Registered onto the main Flask app in server.py
via app.register_blueprint(emcon_scenarios_bp); nothing here changes behavior,
only where the code lives.
"""
from flask import Blueprint, request, jsonify

emcon_scenarios_bp = Blueprint("emcon_scenarios", __name__)


@emcon_scenarios_bp.route("/friday/emcon")
def friday_emcon_status():
    from services.emcon import emcon
    return jsonify(emcon.status())


@emcon_scenarios_bp.route("/friday/emcon/activate", methods=["POST"])
def friday_emcon_activate():
    data = request.get_json(silent=True) or {}
    from services.emcon import emcon
    return jsonify(emcon.activate(data.get("level", 2), data.get("reason", "")))


@emcon_scenarios_bp.route("/friday/emcon/deactivate", methods=["POST"])
def friday_emcon_deactivate():
    from services.emcon import emcon
    return jsonify(emcon.deactivate())


@emcon_scenarios_bp.route("/friday/scenarios/futures", methods=["POST"])
def friday_scenarios_futures():
    data = request.get_json(silent=True) or {}
    from core.scenario_engine import scenario_engine
    return jsonify(scenario_engine.analyze_futures(data.get("situation", ""), data.get("n_scenarios", 6)))


@emcon_scenarios_bp.route("/friday/sokovia/evacuation", methods=["POST"])
def friday_sokovia_evacuation():
    data = request.get_json(silent=True) or {}
    from core.sokovia import sokovia
    return jsonify(sokovia.evacuation_analysis(data.get("situation", ""), data.get("location", ""),
                                               data.get("population", 0)))


@emcon_scenarios_bp.route("/friday/sokovia/safe-action", methods=["POST"])
def friday_sokovia_safe_action():
    data = request.get_json(silent=True) or {}
    from core.sokovia import sokovia
    return jsonify(sokovia.calculate_safe_action(data.get("action", ""), data.get("constraints", [])))
