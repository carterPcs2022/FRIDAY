"""routes/contacts_team.py — Contacts and team coordination routes, split out of the former
monolithic server.py. Registered onto the main Flask app in server.py
via app.register_blueprint(contacts_team_bp); nothing here changes behavior,
only where the code lives.
"""
from flask import Blueprint, request, jsonify

from core.app_state import (
    CONTACTS_OK,
    TEAM_OK,
    friday_contacts,
    team,
)

contacts_team_bp = Blueprint("contacts_team", __name__)


@contacts_team_bp.route("/friday/contacts", methods=["GET"])
def contacts_list():
    if not CONTACTS_OK:
        return jsonify({"error": "contacts unavailable"}), 503
    return jsonify(friday_contacts.get_all())


@contacts_team_bp.route("/friday/contacts/add", methods=["POST"])
def contacts_add():
    if not CONTACTS_OK:
        return jsonify({"error": "contacts unavailable"}), 503
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    return jsonify(friday_contacts.add_contact(
        name, data.get("relationship", "neutral"), data.get("notes", ""),
        email=data.get("email", ""), phone=data.get("phone", ""),
    ))


@contacts_team_bp.route("/friday/contacts/<name>")
def contacts_intel(name):
    if not CONTACTS_OK:
        return jsonify({"error": "contacts unavailable"}), 503
    return jsonify(friday_contacts.get_intel(name))


@contacts_team_bp.route("/friday/team", methods=["GET"])
def team_list():
    if not TEAM_OK:
        return jsonify({"error": "team coordinator unavailable"}), 503
    return jsonify(team.get_all())


@contacts_team_bp.route("/friday/team/update", methods=["POST"])
def team_update():
    if not TEAM_OK:
        return jsonify({"error": "team coordinator unavailable"}), 503
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    return jsonify(team.update_member(name, data.get("status", ""), data.get("task", ""), data.get("location", "")))


@contacts_team_bp.route("/friday/team/brief")
def team_brief_route():
    if not TEAM_OK:
        return jsonify({"error": "team coordinator unavailable"}), 503
    return jsonify({"brief": team.team_brief()})
