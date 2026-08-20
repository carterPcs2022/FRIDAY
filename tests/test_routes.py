"""tests/test_routes.py — route registration regression coverage.

The single most valuable cheap test after a refactor this size: if two
blueprints (or a blueprint and server.py itself) ever define the same
endpoint name, or a blueprint fails to register, Flask either raises at
import time or the route silently never shows up. Importing server.py
successfully is itself a partial assertion here (this whole module
would error at collection if it weren't) — the rest pins the actual
shape so a future change that drops or duplicates a route fails loudly
here instead of showing up as a 404 in production.
"""
KNOWN_ROUTE_COUNT = 162  # 159 as of the blueprint split + 2 memory_hub routes (Phase 2) + /friday/permissions (Phase 3)

# A representative sample across every blueprint, not the full 159 --
# enough to catch "a whole blueprint failed to register" without this
# file needing an update every time a single route is added elsewhere.
EXPECTED_PATHS = [
    "/health", "/login", "/", "/state", "/status", "/command", "/chat",
    "/friday/ask", "/friday/chat/upload", "/friday/vision/analyze",
    "/friday/phone/call", "/friday/phone/text", "/mode", "/friday/protocols",
    "/friday/lockdown", "/friday/hulkbuster/deploy", "/friday/scatter",
    "/friday/health/log", "/friday/medicine/add", "/friday/contacts",
    "/friday/team", "/friday/weather", "/friday/brain/ingest",
    "/friday/tasks", "/friday/workout/log", "/friday/email/send",
    "/friday/goals", "/friday/spotify/auth", "/friday/calendar/today",
    "/friday/habits", "/friday/journal", "/friday/reason/deep",
    "/friday/ooda", "/friday/emcon", "/friday/career/resume",
    "/friday/decisions/analyze", "/friday/finance/stock",
    "/friday/legal/analyze", "/friday/tutor/explain", "/friday/plan",
    "/budget", "/hud", "/friday/memory/recall", "/friday/memory/remember",
    "/friday/permissions",
]

EXPECTED_BLUEPRINTS = {
    "voice_vision", "phone", "orchestration", "security", "health_medicine",
    "contacts_team", "knowledge", "tasks_workouts", "email", "goals",
    "spotify_calendar", "habits_journal", "reasoning", "emcon_scenarios",
    "life_admin", "hud_page",
}


def test_app_imports_without_route_conflicts(app):
    assert app is not None


def test_expected_route_count(app):
    rules = [r for r in app.url_map.iter_rules() if r.rule != "/static/<path:filename>"]
    assert len(rules) == KNOWN_ROUTE_COUNT, (
        f"Expected {KNOWN_ROUTE_COUNT} routes, found {len(rules)} -- a route "
        "was added/removed/duplicated. Update KNOWN_ROUTE_COUNT if intentional."
    )


def test_representative_routes_exist(app):
    registered = {r.rule for r in app.url_map.iter_rules()}
    missing = [p for p in EXPECTED_PATHS if p not in registered]
    assert not missing, f"Missing expected routes: {missing}"


def test_every_blueprint_registered(app):
    assert EXPECTED_BLUEPRINTS.issubset(set(app.blueprints.keys()))


def test_no_duplicate_rule_paths(app):
    """Two different endpoints mapped to the exact same path+methods is
    a real bug (whichever registered second silently wins) that Flask
    itself won't catch, unlike a duplicate endpoint *name*."""
    seen = {}
    dupes = []
    for r in app.url_map.iter_rules():
        key = (r.rule, frozenset(r.methods - {"HEAD", "OPTIONS"}))
        if key in seen and seen[key] != r.endpoint:
            dupes.append((key, seen[key], r.endpoint))
        seen[key] = r.endpoint
    assert not dupes, f"Duplicate route paths mapped to different endpoints: {dupes}"
