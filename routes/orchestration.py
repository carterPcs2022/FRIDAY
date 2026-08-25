"""routes/orchestration.py — JARVIS/system orchestration, protocols, trust, Veronica routes, split out of the former
monolithic server.py. Registered onto the main Flask app in server.py
via app.register_blueprint(orchestration_bp); nothing here changes behavior,
only where the code lives.
"""
from flask import Blueprint, request, jsonify, current_app

from core.permissions import ConfirmationGate, RiskLevel, risk_for
from core.capability_registry import build_registry
from core.policy_engine import policy_engine
from core.app_state import (
    CORE_STATUS,
    PROTOCOLS_OK,
    SELF_REPAIR_OK,
    TRAINING_OK,
    TRAINING_WHEELS_OK,
    VERONICA_OK,
    friday_brain,
    friday_protocols,
    friday_recall,
    friday_remember,
    friday_trainer,
    get_mood_history,
    self_repair,
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


# Two-step like HulkBuster (see routes/security.py's _hulkbuster_gate) --
# both routes below overwrite one of FRIDAY's own core source files on a
# single call, restricted to the fixed FRIDAY_COMPONENTS allowlist (not
# an arbitrary path) but with no confirmation step until this fix.
# Separate gates, not shared -- a pending "confirm this repair" token
# must not be able to confirm a contain instead, or vice versa (same
# "one gate per action" reasoning core/permissions.py documents).
# veronica.monitor()'s own automatic repairs call deploy_replacement()
# directly, bypassing this route entirely -- self-healing still needs
# to work with no human in the loop; only the manual API trigger does.
_veronica_repair_gate = ConfirmationGate("Veronica manual repair")
_veronica_contain_gate = ConfirmationGate("Veronica manual containment")


@orchestration_bp.route("/friday/veronica/repair/<component>", methods=["POST"])
def veronica_repair(component):
    """Restore a component from its saved backup. Returns
    repaired=False with no backup available — never improvises a
    replacement."""
    if not VERONICA_OK:
        return jsonify({"error": "veronica unavailable"}), 503
    data = request.get_json(silent=True) or {}
    confirm_token = data.get("confirm_token", "")
    if not confirm_token:
        return jsonify(_veronica_repair_gate.request())
    if not _veronica_repair_gate.confirm(confirm_token):
        return jsonify({"error": "confirmation missing or expired — request again"}), 400
    return jsonify(veronica.deploy_replacement(component, "manual"))


@orchestration_bp.route("/friday/veronica/contain/<component>", methods=["POST"])
def veronica_contain(component):
    """Manual-only: swap a component for a harmless no-op stub, backing
    up the original first."""
    if not VERONICA_OK:
        return jsonify({"error": "veronica unavailable"}), 503
    data = request.get_json(silent=True) or {}
    confirm_token = data.get("confirm_token", "")
    if not confirm_token:
        return jsonify(_veronica_contain_gate.request())
    if not _veronica_contain_gate.confirm(confirm_token):
        return jsonify({"error": "confirmation missing or expired — request again"}), 400
    return jsonify(veronica.contain_failing_component(component))


# ── Self-repair: diagnose a real logic bug (not file corruption --
# Veronica already handles that), propose and sandbox-test a minimal fix,
# then stage it. See core/self_repair.py for why the live file is never
# touched without a human confirming. ────────────────────────────────────

@orchestration_bp.route("/friday/self_repair/run", methods=["POST"])
def self_repair_run():
    if not SELF_REPAIR_OK:
        return jsonify({"error": "self-repair unavailable"}), 503
    return jsonify(self_repair.attempt_repair())


@orchestration_bp.route("/friday/self_repair/confirm", methods=["POST"])
def self_repair_confirm():
    if not SELF_REPAIR_OK:
        return jsonify({"error": "self-repair unavailable"}), 503
    data = request.get_json(silent=True) or {}
    return jsonify(self_repair.confirm_repair(data.get("confirm_token")))


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


# ── V3 migration: Capability Registry (Phase 3) + Policy Engine
# (Phase 5) -- see core/capability_registry.py and core/policy_engine.py
# for what these do and deliberately don't do. ─────────────────────────

@orchestration_bp.route("/friday/capabilities")
def capabilities_list():
    """What can FRIDAY do, and is it usable right now -- built fresh
    from the live route table + CAPABILITY_MAP each call, same
    introspect-don't-hand-maintain approach as /friday/permissions
    above. ?category= filters (e.g. ?category=email, ?category=mcu_capability)."""
    registry = build_registry(current_app.url_map)
    category = request.args.get("category")
    capabilities = registry.by_category(category) if category else registry.all()
    return jsonify({
        "count": len(capabilities),
        "capabilities": [
            {
                "name": c.name, "description": c.description, "category": c.category,
                "risk_level": c.risk_level.name, "source": c.source,
                "reversible": c.reversible, "requires_confirmation": c.requires_confirmation,
                "simulated": c.simulated, "available": c.is_available(),
            }
            for c in capabilities
        ],
    })


@orchestration_bp.route("/friday/policy/evaluate", methods=["POST"])
def policy_evaluate():
    """Runs a named capability (from /friday/capabilities) through the
    PolicyEngine and returns ALLOW / DENY / CONFIRM. Doesn't execute
    anything itself -- this answers "would this be allowed," the same
    question every DESTRUCTIVE route already answers internally via its
    own ConfirmationGate, just generalized to any registered capability."""
    data = request.get_json(silent=True) or {}
    name = data.get("capability", "")
    registry = build_registry(current_app.url_map)
    capability = registry.get(name)
    if capability is None:
        return jsonify({"error": f"unknown capability: {name!r}"}), 404
    result = policy_engine.evaluate(capability, confirm_token=data.get("confirm_token"))
    return jsonify(result.to_dict())


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
