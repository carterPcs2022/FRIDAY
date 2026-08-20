"""routes/security.py — Lockdown, HulkBuster, Scatter Protocol routes, split out of the former
monolithic server.py. Registered onto the main Flask app in server.py
via app.register_blueprint(security_bp); nothing here changes behavior,
only where the code lives.
"""
from flask import Blueprint, request, jsonify

from core.app_state import (
    HULKBUSTER_OK,
    LOCKDOWN_OK,
    SCATTER_OK,
    SECURITY_OK,
    friday_security,
    hulkbuster,
    scatter_engine,
    suit_lockdown,
)
from core.permissions import ConfirmationGate

security_bp = Blueprint("security", __name__)

# Unlike Scatter (its own passphrase-bound 2-step) and lockdown
# (deliberately frictionless -- see core/permissions.py), a manual
# HulkBuster deploy had no confirmation step at all: one authenticated
# POST immediately blocked an IP and triggered suit_lockdown. The
# automatic 3-threats escalation path (friday_security._maybe_escalate())
# doesn't go through this route at all, so this gate only adds friction
# to a human deliberately calling the API directly -- not to the
# automated response.
_hulkbuster_gate = ConfirmationGate("HulkBuster deployment")


@security_bp.route("/friday/lockdown", methods=["POST"])
def trigger_lockdown():
    if not LOCKDOWN_OK:
        return jsonify({"error": "lockdown unavailable"}), 503
    return jsonify(suit_lockdown.activate(reason="remote_trigger"))


@security_bp.route("/friday/hulkbuster/status")
def hulkbuster_status():
    if not HULKBUSTER_OK:
        return jsonify({"error": "hulkbuster unavailable"}), 503
    return jsonify(hulkbuster.status())


@security_bp.route("/friday/hulkbuster/deploy", methods=["POST"])
def hulkbuster_deploy():
    """Two-step like Scatter: POST without confirm_token gets you a
    token; POST again with that same token within 10 minutes actually
    deploys. See _hulkbuster_gate above for why this route specifically
    gets it and /friday/lockdown deliberately doesn't."""
    if not HULKBUSTER_OK:
        return jsonify({"error": "hulkbuster unavailable"}), 503
    data = request.get_json(silent=True) or {}
    confirm_token = data.get("confirm_token", "")
    if not confirm_token:
        return jsonify(_hulkbuster_gate.request())
    if not _hulkbuster_gate.confirm(confirm_token):
        return jsonify({"error": "confirmation missing or expired — request again"}), 400
    return jsonify(hulkbuster.deploy(data.get("reason", "manual"), data.get("ip", "")))


@security_bp.route("/friday/hulkbuster/stand-down", methods=["POST"])
def hulkbuster_stand_down():
    if not HULKBUSTER_OK:
        return jsonify({"error": "hulkbuster unavailable"}), 503
    return jsonify(hulkbuster.stand_down())


@security_bp.route("/friday/scatter", methods=["POST"])
def trigger_scatter():
    if not SCATTER_OK:
        return jsonify({"error": "scatter unavailable"}), 503
    data = request.get_json(silent=True) or {}
    passphrase = data.get("passphrase", "")
    confirm_token = data.get("confirm_token", "")
    if not passphrase:
        return jsonify({"error": "passphrase required"}), 400
    if not confirm_token:
        return jsonify(scatter_engine.request_scatter(passphrase))
    result = scatter_engine.scatter(passphrase, confirm_token)
    if not result.get("ok"):
        return jsonify(result), 400
    return jsonify(result)


@security_bp.route("/friday/scatter/status")
def scatter_status():
    if not SCATTER_OK:
        return jsonify({"error": "scatter unavailable"}), 503
    return jsonify(scatter_engine.status())


@security_bp.route("/friday/scatter/reassemble", methods=["POST"])
def scatter_reassemble():
    if not SCATTER_OK:
        return jsonify({"error": "scatter unavailable"}), 503
    data = request.get_json(silent=True) or {}
    passphrase = data.get("passphrase", "")
    if not passphrase:
        return jsonify({"error": "passphrase required"}), 400
    result = scatter_engine.reassemble(passphrase)
    if not result.get("ok"):
        return jsonify(result), 400
    return jsonify(result)


@security_bp.route("/friday/scatter/nodes")
def scatter_nodes_list():
    if not SCATTER_OK:
        return jsonify({"error": "scatter unavailable"}), 503
    from services.scatter_nodes import get_nodes
    nodes = get_nodes()
    return jsonify({"nodes": [{"name": n.name, "available": n.available()} for n in nodes]})


@security_bp.route("/friday/security/status")
def security_status():
    if not SECURITY_OK:
        return jsonify({"error": "security unavailable"}), 503
    return jsonify(friday_security.get_threat_summary())
