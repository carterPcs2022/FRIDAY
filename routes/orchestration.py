"""routes/orchestration.py — JARVIS/system orchestration, protocols, trust, Veronica routes, split out of the former
monolithic server.py. Registered onto the main Flask app in server.py
via app.register_blueprint(orchestration_bp); nothing here changes behavior,
only where the code lives.
"""
from flask import Blueprint, request, jsonify, current_app

from core.permissions import RiskLevel, risk_for
from core.app_state import (
    CAPABILITIES_OK,
    CAPABILITY_MAP,
    CORE_STATUS,
    PROTOCOLS_OK,
    TRAINING_OK,
    TRAINING_WHEELS_OK,
    VERONICA_OK,
    friday_brain,
    friday_protocols,
    friday_recall,
    friday_remember,
    friday_trainer,
    get_mood_history,
    training_wheels,
    veronica,
)

orchestration_bp = Blueprint("orchestration", __name__)


@orchestration_bp.route("/mode", methods=["POST"])
def set_mode():
    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "normal")
    if friday_brain:
        friday_brain.set_voice_mode(mode)
    return jsonify({"mode": mode, "status": "set"})


@orchestration_bp.route("/friday/protocols")
def list_protocols():
    if not PROTOCOLS_OK:
        return jsonify({"error": "protocols unavailable"}), 503
    from core.friday_protocols import FRIDAY_PROTOCOLS
    return jsonify({"protocols": FRIDAY_PROTOCOLS, "current_range": friday_protocols.range_level.value})


@orchestration_bp.route("/friday/protocols/<int:n>", methods=["POST"])
def run_protocol(n):
    if not PROTOCOLS_OK:
        return jsonify({"error": "protocols unavailable"}), 503
    return jsonify(friday_protocols.run_protocol(n))


@orchestration_bp.route("/friday/range")
def range_status():
    if not PROTOCOLS_OK:
        return jsonify({"error": "protocols unavailable"}), 503
    return jsonify(friday_protocols.get_range_report())


@orchestration_bp.route("/friday/training/sync", methods=["POST"])
def training_sync():
    if not TRAINING_OK:
        return jsonify({"error": "training unavailable"}), 503
    return jsonify(friday_trainer.sync_from_jarvis())


@orchestration_bp.route("/friday/training/status")
def training_status():
    if not TRAINING_OK:
        return jsonify({"error": "training unavailable"}), 503
    return jsonify(friday_trainer.status())


@orchestration_bp.route("/friday/mood")
def mood_history():
    if not CORE_STATUS == "online":
        return jsonify({"error": "memory unavailable"}), 503
    days = request.args.get("days", 7, type=int)
    return jsonify(get_mood_history(days))


@orchestration_bp.route("/friday/remember", methods=["POST"])
def remember():
    data = request.get_json(silent=True) or {}
    key, value = data.get("key", "").strip(), data.get("value", "").strip()
    if not key or not value:
        return jsonify({"error": "key and value required"}), 400
    friday_remember(key, value)
    return jsonify({"status": "remembered", "key": key})


@orchestration_bp.route("/friday/recall")
def recall():
    key = request.args.get("key", "").strip()
    if not key:
        return jsonify({"error": "key required"}), 400
    value = friday_recall(key)
    return jsonify({"key": key, "value": value})


@orchestration_bp.route("/friday/veronica/status")
def veronica_status():
    if not VERONICA_OK:
        return jsonify({"error": "veronica unavailable"}), 503
    return jsonify(veronica.get_status())


@orchestration_bp.route("/friday/veronica/selftest")
def veronica_selftest():
    if not VERONICA_OK:
        return jsonify({"error": "veronica unavailable"}), 503
    return jsonify(veronica.self_test())


@orchestration_bp.route("/friday/veronica/monitor", methods=["POST"])
def veronica_monitor():
    if not VERONICA_OK:
        return jsonify({"error": "veronica unavailable"}), 503
    return jsonify(veronica.monitor())


@orchestration_bp.route("/friday/veronica/baselines", methods=["POST"])
def veronica_baselines():
    if not VERONICA_OK:
        return jsonify({"error": "veronica unavailable"}), 503
    return jsonify(veronica.save_baselines())


@orchestration_bp.route("/friday/veronica/repair/<component>", methods=["POST"])
def veronica_repair(component):
    """Restore a component from its saved backup. Returns
    repaired=False with no backup available — never improvises a
    replacement."""
    if not VERONICA_OK:
        return jsonify({"error": "veronica unavailable"}), 503
    return jsonify(veronica.deploy_replacement(component, "manual"))


@orchestration_bp.route("/friday/veronica/contain/<component>", methods=["POST"])
def veronica_contain(component):
    """Manual-only: swap a component for a harmless no-op stub, backing
    up the original first."""
    if not VERONICA_OK:
        return jsonify({"error": "veronica unavailable"}), 503
    return jsonify(veronica.contain_failing_component(component))


@orchestration_bp.route("/friday/capabilities")
def list_capabilities():
    if not CAPABILITIES_OK:
        return jsonify({"error": "capabilities unavailable"}), 503
    return jsonify({"triggers": list(CAPABILITY_MAP.keys())})


@orchestration_bp.route("/friday/permissions")
def permissions_status():
    """Introspects the live route table and classifies every registered
    route by risk tier (core/permissions.py) -- the actual current
    classification, not a hand-maintained list that can drift from what's
    really registered."""
    by_tier = {level.name: [] for level in RiskLevel}
    for rule in current_app.url_map.iter_rules():
        if rule.rule == "/static/<path:filename>":
            continue
        tier = risk_for(rule.endpoint, rule.methods - {"HEAD", "OPTIONS"})
        by_tier[tier.name].append(rule.rule)
    for paths in by_tier.values():
        paths.sort()
    return jsonify({
        "tiers": by_tier,
        "counts": {k: len(v) for k, v in by_tier.items()},
    })


@orchestration_bp.route("/friday/trust")
def trust_status():
    if not TRAINING_WHEELS_OK:
        return jsonify({"error": "training wheels unavailable"}), 503
    return jsonify(training_wheels.status())


@orchestration_bp.route("/friday/trust/set", methods=["POST"])
def set_trust():
    if not TRAINING_WHEELS_OK:
        return jsonify({"error": "training wheels unavailable"}), 503
    data = request.get_json() or {}
    score = max(0, min(100, int(data.get("score", 50))))
    training_wheels._data["trust"] = score
    training_wheels._save()
    return jsonify({"trust": score})


@orchestration_bp.route("/friday/system/config-check")
def friday_config_check():
    from core.config_validator import check
    return jsonify(check())


@orchestration_bp.route("/friday/system/doctor")
def friday_system_doctor():
    from services import system_doctor
    return jsonify(system_doctor.full_check())


@orchestration_bp.route("/friday/system/cleanup", methods=["POST"])
def friday_system_cleanup():
    from services import disk_cleanup
    return jsonify(disk_cleanup.clean())
