"""core/config_validator.py — sanity-checks the env config FRIDAY actually
boots with, since a misconfigured deploy (placeholder API key left in,
Mac Bridge URL still pointing at localhost, a token set with no matching
URL) otherwise just fails silently downstream in whatever service tries
to use it, hours later, far from the actual cause.
"""
import logging
import os

# Keys worth checking for "did the boss forget to replace the placeholder"
# — anything the repo's various services read via os.environ.get/os.getenv.
_API_KEYS = [
    "ANTHROPIC_API_KEY", "GROQ_API_KEY", "ELEVENLABS_API_KEY",
    "PUSHOVER_USER_KEY", "PUSHOVER_APP_TOKEN",
    "JARVIS_API_TOKEN", "MAC_BRIDGE_TOKEN",
    "EMAIL_ADDRESS", "EMAIL_PASSWORD",
    "SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET",
    "GOOGLE_CALENDAR_CLIENT_ID", "GOOGLE_CALENDAR_CLIENT_SECRET",
    "GOOGLE_GMAIL_CLIENT_ID", "GOOGLE_GMAIL_CLIENT_SECRET",
    "SERPER_API_KEY", "TAVILY_API_KEY", "SERPAPI_KEY",
    "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE",
    "TURSO_AUTH_TOKEN", "HA_TOKEN", "PUSHCUT_API_KEY", "FRIDAY_ACCESS_TOKEN",
]

# Values people paste in as stand-ins and then forget to swap out.
_PLACEHOLDER_STRINGS = [
    "your_api_key", "your-api-key", "changeme", "change_me", "xxx",
    "placeholder", "todo", "replace_me", "replace-me", "example",
    "sk-xxxx", "insert_key_here",
]

# URL-shaped env vars that must actually be reachable off this box in
# production — a Render deploy pointing at localhost/127.0.0.1 means
# whoever set it never updated it after copying from a local .env.
_URL_KEYS = [
    "MAC_BRIDGE_URL", "JARVIS_URL", "GOOGLE_CALENDAR_REDIRECT_URI",
    "GOOGLE_GMAIL_REDIRECT_URI", "HA_URL", "PUSHCUT_MOM_WEBHOOK_URL",
]

# (url_key, token_key) pairs. Which half is missing changes how bad it
# is -- see the asymmetry in check(): a URL with no token is broken, a
# token with no URL is just an integration that's off.
_PAIRED_KEYS = [
    ("MAC_BRIDGE_URL", "MAC_BRIDGE_TOKEN"),
    ("PUSHOVER_USER_KEY", "PUSHOVER_APP_TOKEN"),
    ("JARVIS_URL", "JARVIS_API_TOKEN"),
    ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET"),
    ("GOOGLE_CALENDAR_CLIENT_ID", "GOOGLE_CALENDAR_CLIENT_SECRET"),
    ("GOOGLE_GMAIL_CLIENT_ID", "GOOGLE_GMAIL_CLIENT_SECRET"),
    ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"),
    ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN"),
    ("HA_URL", "HA_TOKEN"),
    ("EMAIL_ADDRESS", "EMAIL_PASSWORD"),
]


def _is_placeholder(value: str) -> bool:
    v = value.lower()
    return any(p in v for p in _PLACEHOLDER_STRINGS)


def _is_localhost_in_prod(value: str) -> bool:
    # Render sets RENDER automatically on its own boxes — nothing else in
    # this repo already tracks "am I in production", so this is the one
    # honest signal available rather than inventing a second env flag.
    if not os.environ.get("RENDER", ""):
        return False
    v = value.lower()
    return "localhost" in v or "127.0.0.1" in v


def check() -> dict:
    """Returns {"ok": bool, "issues": [...], "notes": [...]}. Never raises
    — a broken validator must not be the thing that takes the boot down.

    issues are things that will actually misbehave and are worth an alert.
    notes are worth seeing but not worth waking anyone for; `ok` and the
    alert in check_and_alert() key off issues only."""
    issues = []
    notes = []

    try:
        seen_values = {}
        for key in _API_KEYS:
            value = os.environ.get(key, "")
            if not value:
                continue
            if _is_placeholder(value):
                issues.append(f"{key} looks like a placeholder value, not a real credential")
            # Duplicate detection — two different keys sharing one value
            # usually means a copy-paste left one unset for real.
            if value in seen_values:
                issues.append(f"{key} has the same value as {seen_values[value]} — likely a copy-paste leftover")
            else:
                seen_values[value] = key

        for key in _URL_KEYS:
            value = os.environ.get(key, "")
            if not value:
                continue
            if not (value.startswith("http://") or value.startswith("https://")):
                issues.append(f"{key} doesn't look like a URL: {value!r}")
            elif _is_localhost_in_prod(value):
                issues.append(f"{key} points at localhost while running in production (RENDER is set)")

        # The two halves of a pair are not equally broken, and treating
        # them the same made FRIDAY email a HIGH-priority "Config Check
        # Failed" every boot over a leftover MAC_BRIDGE_TOKEN -- now every
        # 30 minutes, since she stopped being spun down between requests.
        #
        #   URL without token  -> she will call it and fail to
        #                         authenticate. Genuinely broken.
        #   token without URL  -> there is nothing to call. The
        #                         integration is simply off, which is
        #                         indistinguishable from never having
        #                         configured it.
        #
        # The second is a stray credential worth knowing about, not a
        # failure worth waking the boss for. It stays visible as a note;
        # it just stops being an alert. An alert nobody can act on is one
        # they learn to ignore, which costs more than it's worth the day
        # a real one arrives.
        for url_key, token_key in _PAIRED_KEYS:
            has_url = bool(os.environ.get(url_key, ""))
            has_token = bool(os.environ.get(token_key, ""))
            if has_url and not has_token:
                issues.append(
                    f"{url_key} is set but {token_key} isn't — that pair only works together"
                )
            elif has_token and not has_url:
                notes.append(
                    f"{token_key} is set but {url_key} isn't — that integration is "
                    f"off, nothing will use the credential"
                )

        # Unlike every other key above, FRIDAY_ACCESS_TOKEN being unset
        # isn't "that integration is disabled" — it means /command and
        # every other data-touching route has zero authentication, not a
        # degraded feature. Worth its own explicit flag, not just silence.
        if not os.environ.get("FRIDAY_ACCESS_TOKEN", ""):
            issues.append(
                "FRIDAY_ACCESS_TOKEN is not set — /command and other routes are "
                "completely unauthenticated; anyone with the URL can talk to FRIDAY "
                "and read personal data"
            )
    except Exception as e:
        issues.append(f"config validator itself failed: {e}")

    return {"ok": not issues, "issues": issues, "notes": notes}


def check_and_alert():
    """Called once at startup. Only alerts on failure — a clean config
    check is not something worth waking anyone up for."""
    result = check()
    # Notes are logged, never alerted -- they describe config that is off
    # rather than broken, and an alert nobody can act on is one they learn
    # to ignore.
    for note in result.get("notes", []):
        logging.info("[config] %s", note)
    if result["ok"]:
        return result
    try:
        from services.notifications import alert
        alert("FRIDAY Config Check Failed", "; ".join(result["issues"])[:1024])
    except Exception:
        pass
    return result
