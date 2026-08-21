"""routes/hud_page.py — Budget status and the HUD frontend page routes, split out of the former
monolithic server.py. Registered onto the main Flask app in server.py
via app.register_blueprint(hud_page_bp); nothing here changes behavior,
only where the code lives.

The HUD page itself used to be a ~1800-line inline HTML/CSS/JS string
returned directly from the /hud route. Moved to templates/hud.html +
static/css/hud.css + static/js/hud.js + static/js/hud_reticle.js -- real
Flask template/static files, browser-cacheable and editable without
touching Python. FRIDAY_HUD_HTML had zero server-side interpolation (it
was a plain string, not an f-string), so this is a byte-for-byte
relocation, not a rewrite.
"""
from flask import Blueprint, jsonify, render_template

hud_page_bp = Blueprint("hud_page", __name__)


@hud_page_bp.route("/budget")
def budget_status():
    try:
        import budget_2 as budget
        return jsonify(budget.status())
    except Exception as e:
        return jsonify({"error": str(e)})


@hud_page_bp.route("/hud")
def hud():
    return render_template("hud.html")
