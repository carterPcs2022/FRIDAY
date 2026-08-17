"""core/config_validator.py — sanity-checks the env config FRIDAY actually
boots with, since a misconfigured deploy (placeholder API key left in,
Mac Bridge URL still pointing at localhost, a token set with no matching
URL) otherwise just fails silently downstream in whatever service tries
to use it, hours later, far from the actual cause.
"""
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
    "SERPER_API_KEY", "TAVILY_API_KEY", "SERPAPI_KEY",
    "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE",
    "TURSO_AUTH_TOKEN", "HA_TOKEN",
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
_URL_KEYS = ["MAC_BRIDGE_URL", "JARVIS_URL", "GOOGLE_CALENDAR_REDIRECT_URI", "HA_URL"]

# (url_key, token_key) pairs — one configured without the other is
# always a mistake, since either FRIDAY has no bridge to call or it has
# a bridge it can't authenticate to.
_PAIRED_KEYS = [
    ("MAC_BRIDGE_URL", "MAC_BRIDGE_TOKEN"),
    ("PUSHOVER_USER_KEY", "PUSHOVER_APP_TOKEN"),
    ("JARVIS_URL", "JARVIS_API_TOKEN"),
    ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET"),
    ("GOOGLE_CALENDAR_CLIENT_ID", "GOOGLE_CALENDAR_CLIENT_SECRET"),
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
    """Returns {"ok": bool, "issues": [str, ...]}. Never raises — a broken
    validator must not be the thing that takes the boot down."""
    issues = []

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

        for url_key, token_key in _PAIRED_KEYS:
            has_url = bool(os.environ.get(url_key, ""))
            has_token = bool(os.environ.get(token_key, ""))
            if has_url != has_token:
                present, missing = (url_key, token_key) if has_url else (token_key, url_key)
                issues.append(f"{present} is set but {missing} isn't — that pair only works together")
    except Exception as e:
        issues.append(f"config validator itself failed: {e}")

    return {"ok": not issues, "issues": issues}


def check_and_alert():
    """Called once at startup. Only alerts on failure — a clean config
    check is not something worth waking anyone up for."""
    result = check()
    if result["ok"]:
        return result
    try:
        from core.friday_capabilities import friday_caps
        friday_caps._pushover_alert(
            "FRIDAY Config Check Failed",
            "; ".join(result["issues"])[:1024],
        )
    except Exception:
        pass
    return result
