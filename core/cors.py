"""core/cors.py — cross-origin access, allow-listed and credential-free.

FRIDAY's HUD is served from the same origin as her API, so nothing ever
needed CORS. A page on another origin -- a Claude artifact, say -- is
blocked by the browser before the request reaches her at all.

Opening that up on this particular server needs care. She reads the
boss's email, calendar, notes and location. Three deliberate choices:

  No wildcard. "*" would let any page on the internet call her. The
  allow-list is explicit and comes from FRIDAY_CORS_ORIGINS.

  No credentials. Access-Control-Allow-Credentials is never sent, so a
  browser will not attach the friday_auth session cookie to a
  cross-origin request. That closes the shape where a malicious page
  rides the boss's logged-in session while he happens to be visiting it.
  Cross-origin callers authenticate by putting FRIDAY_ACCESS_TOKEN in an
  Authorization header, which only something he deliberately handed the
  token to can do.

  Rejections are logged with the origin, and the last few are kept in
  memory for /cors-check to read back. A sandboxed iframe can report its
  origin as "null" or as a per-page domain, and guessing wrong costs a
  round of "try it again" -- so she records what actually arrived and the
  right value can be read off instead of guessed.
"""
import logging
import os
import threading
import time

# Comma-separated. Empty (the default) means no cross-origin access at
# all, which is the behavior every deploy has had until now.
_RAW = os.getenv("FRIDAY_CORS_ORIGINS", "")
ALLOWED_ORIGINS = {o.strip() for o in _RAW.split(",") if o.strip()}

# Preflight asks about these before the browser will send the real
# request. Authorization is what a cross-origin caller uses in place of
# the cookie.
_ALLOW_HEADERS = "Content-Type, Authorization"
_ALLOW_METHODS = "GET, POST, OPTIONS"


# Recent rejections, newest first, so /cors-check can read back the exact
# origin that was turned away. Bounded because this is a diagnostic, not a
# log: the value of interest is always the most recent attempt, and an
# unbounded dict here would grow forever on a long-lived process being
# probed from the open internet.
_MAX_BLOCKED = 10
_blocked_lock = threading.Lock()
_blocked = {}  # origin -> {"count": int, "last_seen": float}


def is_allowed(origin: str) -> bool:
    return bool(origin) and origin in ALLOWED_ORIGINS


def _record_blocked(origin: str):
    with _blocked_lock:
        entry = _blocked.get(origin)
        if entry is None:
            # Evict the least recently seen rather than the oldest-added:
            # a page retrying its handshake should not be aged out by a
            # burst of one-off probes that arrived after it.
            if len(_blocked) >= _MAX_BLOCKED:
                oldest = min(_blocked, key=lambda o: _blocked[o]["last_seen"])
                del _blocked[oldest]
            entry = _blocked[origin] = {"count": 0, "last_seen": 0.0}
        entry["count"] += 1
        entry["last_seen"] = time.time()


def blocked_origins() -> list:
    """Recently rejected origins, most recent first."""
    with _blocked_lock:
        items = [
            {"origin": o, "count": e["count"], "last_seen": e["last_seen"]}
            for o, e in _blocked.items()
        ]
    items.sort(key=lambda i: i["last_seen"], reverse=True)
    return items


def apply(response, origin: str):
    """Attach CORS headers when `origin` is allow-listed. Returns the
    response either way, so callers can use it unconditionally."""
    if not origin:
        return response

    if not is_allowed(origin):
        # The whole point of logging this: the exact value is hard to
        # predict for sandboxed pages, and it's the one thing needed to
        # allow-list correctly.
        logging.warning(
            "[cors] blocked origin %r — add it to FRIDAY_CORS_ORIGINS to allow", origin
        )
        _record_blocked(origin)
        return response

    response.headers["Access-Control-Allow-Origin"] = origin
    # Same URL answers differently per origin; without this a shared
    # cache could hand one origin's headers to another.
    response.headers["Vary"] = "Origin"
    response.headers["Access-Control-Allow-Methods"] = _ALLOW_METHODS
    response.headers["Access-Control-Allow-Headers"] = _ALLOW_HEADERS
    response.headers["Access-Control-Max-Age"] = "600"
    # Access-Control-Allow-Credentials is deliberately absent -- see the
    # module docstring.
    return response
