"""tests/test_hud_page.py — /hud used to return a ~1800-line inline
HTML/CSS/JS string built by hand in routes/hud_page.py. Moved to a real
Flask template (templates/hud.html) plus static/css/hud.css,
static/js/hud.js, static/js/hud_reticle.js. These tests guard the two
things that extraction could silently break: the template/static files
actually resolving at request time, and no literal `{{`/`{%` surviving
into the served page (the original string was returned raw, never passed
through Jinja, so any stray Jinja-looking syntax in the CSS/JS would only
surface once it started being rendered as a template).
"""


class TestHudPage:
    def test_hud_route_serves_rendered_template(self, client):
        resp = client.get("/hud")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "<title>F.R.I.D.A.Y</title>" in html
        assert "/static/css/hud.css" in html
        assert "/static/js/hud.js" in html
        assert "/static/js/hud_reticle.js" in html

    def test_no_unrendered_jinja_syntax_leaks_into_the_page(self, client):
        html = client.get("/hud").get_data(as_text=True)
        assert "{{" not in html
        assert "{%" not in html

    def test_hud_css_is_served(self, client):
        resp = client.get("/static/css/hud.css")
        assert resp.status_code == 200
        assert b":root" in resp.get_data()

    def test_hud_js_is_served(self, client):
        resp = client.get("/static/js/hud.js")
        assert resp.status_code == 200
        assert b"function send" in resp.get_data()

    def test_hud_reticle_js_is_served(self, client):
        resp = client.get("/static/js/hud_reticle.js")
        assert resp.status_code == 200
        assert b"setHudThreatState" in resp.get_data()

    def test_budget_route_unaffected_by_the_split(self, client):
        resp = client.get("/budget")
        assert resp.status_code == 200
