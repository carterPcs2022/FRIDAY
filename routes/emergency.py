"""routes/emergency.py — emergency alert API (see services/friday_emergency.py).

Auth: protected by the global access gate like every other route, AND each view
refuses to run at all when FRIDAY_ACCESS_TOKEN is unset. The global gate fails
OPEN in that state ("don't lock the boss out before he's configured it"),
which is fine for reading a calendar but not for an endpoint that sends texts to
your family.
"""
import functools

from flask import Blueprint, jsonify, request

emergency_bp = Blueprint("emergency", __name__)


def _auth_required(view):
    @functools.wraps(view)
    def wrapper(*a, **k):
        from core import access_auth
        if not access_auth.is_configured():
            return jsonify({"error": "FRIDAY_ACCESS_TOKEN is not set; emergency routes are disabled until it is."}), 503
        return view(*a, **k)
    return wrapper


def _mgr():
    from services import friday_emergency
    return friday_emergency.emergency


def _num(value, lo, hi, name):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not (lo <= float(value) <= hi):
        raise ValueError(f"'{name}' must be a number between {lo} and {hi}")
    return float(value)


@emergency_bp.route("/api/emergency/status")
@_auth_required
def emergency_status():
    return jsonify({**_mgr().readiness(), "latest": _mgr().latest()})


@emergency_bp.route("/api/emergency/trigger", methods=["POST"])
@_auth_required
def emergency_trigger():
    body = request.get_json(silent=True)
    body = body if isinstance(body, dict) else {}
    try:
        lat, lon = _num(body.get("lat"), -90, 90, "lat"), _num(body.get("lon"), -180, 180, "lon")
        accuracy = _num(body.get("accuracy"), 0, 100000, "accuracy")
        countdown = _num(body.get("countdown"), 0, 3600, "countdown")
        if (lat is None) != (lon is None):
            raise ValueError("send both 'lat' and 'lon', or neither")
        if body.get("drill") not in (None, True, False):
            raise ValueError("'drill' must be true or false")
        if body.get("reason") is not None and not isinstance(body["reason"], str):
            raise ValueError("'reason' must be text")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    result = _mgr().trigger(reason=body.get("reason") or "", lat=lat, lon=lon, accuracy=accuracy,
                            drill=bool(body.get("drill")), countdown=countdown, source="api")
    return jsonify(result), (429 if result.get("state") == "rate_limited" else 200)


@emergency_bp.route("/api/emergency/cancel", methods=["POST"])
@_auth_required
def emergency_cancel():
    body = request.get_json(silent=True)
    alert_id = body.get("id") if isinstance(body, dict) else None
    return jsonify(_mgr().cancel(alert_id if isinstance(alert_id, str) else None))


@emergency_bp.route("/api/emergency/send_now", methods=["POST"])
@_auth_required
def emergency_send_now():
    body = request.get_json(silent=True)
    alert_id = body.get("id") if isinstance(body, dict) else None
    return jsonify(_mgr().send_now(alert_id if isinstance(alert_id, str) else None))


@emergency_bp.route("/api/emergency/alert/<alert_id>")
@_auth_required
def emergency_alert(alert_id):
    a = _mgr().get(alert_id)
    return (jsonify(a), 200) if a else (jsonify({"error": "unknown alert"}), 404)


@emergency_bp.route("/api/emergency/location", methods=["POST"])
@_auth_required
def emergency_location():
    """Attach a position to the live (pending) alert. Lets the client start the countdown the instant
    the button is held and add the fix once the GPS has one."""
    body = request.get_json(silent=True)
    body = body if isinstance(body, dict) else {}
    try:
        lat, lon = _num(body.get("lat"), -90, 90, "lat"), _num(body.get("lon"), -180, 180, "lon")
        accuracy = _num(body.get("accuracy"), 0, 100000, "accuracy")
        if lat is None or lon is None:
            raise ValueError("'lat' and 'lon' are both required")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    alert_id = body.get("id")
    return jsonify(_mgr().update_location(alert_id if isinstance(alert_id, str) else None, lat, lon, accuracy))
