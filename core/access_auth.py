"""core/access_auth.py — the boss-only access gate.

Before this, /command and every other route touching real data (journal,
bills, decisions, second_brain, calendar, relationships, finances — all
of it) had zero authentication. Anyone who found the Render URL could
talk to FRIDAY and pull personal data with no credential at all;
friday_security.py's rate-limiting and injection screening stop abuse
patterns, not identity. This closes that gap with a shared-secret check
in front of everything except deliberately open routes and Twilio
callbacks, which are separately authenticated with Twilio request signatures. (suit_lockdown's trigger, meant to work from
a device that's never touched this account before).

Cookie-based rather than requiring every one of ~150 routes' fetch()
calls in the HUD page to be rewritten with an Authorization header: log
in once at /login, the browser carries the session cookie automatically
on every same-origin request after that. API-style callers (curl, a
Shortcut, a script) can instead pass the raw token via an Authorization
header or ?token= query param — checked directly against
FRIDAY_ACCESS_TOKEN, no session needed.

Deliberately does nothing (is_configured() False, gate never fires) if
FRIDAY_ACCESS_TOKEN isn't set — matches every other optional-integration
convention in this repo (check-key-before-gating), so an unconfigured
deploy isn't locked out before the boss has had a chance to set it.
config_validator.py already flags an unset token as a config issue.
"""
import hashlib
import hmac
import os

ACCESS_TOKEN = os.environ.get("FRIDAY_ACCESS_TOKEN", "")
SESSION_COOKIE = "friday_auth"

# Paths reachable with no session or token — either they use their own
# verified signature (Twilio callbacks) or are deliberately open by design (lockdown, health checks
# for uptime monitors, the status JSON at "/" which carries no personal
# data, and /login itself).
EXEMPT_PATHS = {
    "/", "/health", "/login",
    "/friday/lockdown",
}


def is_configured() -> bool:
    return bool(ACCESS_TOKEN)


def is_exempt(path: str) -> bool:
    return path in EXEMPT_PATHS


def check_token(token: str) -> bool:
    """Constant-time comparison against the raw token — timing attacks
    against a string this short and this consequential aren't
    theoretical, and hmac.compare_digest costs nothing to use here."""
    if not ACCESS_TOKEN or not token:
        return False
    return hmac.compare_digest(token, ACCESS_TOKEN)


def _session_value() -> str:
    # Derived from the token, not the raw token itself — the cookie
    # shouldn't literally be the credential, so a cookie logged/leaked
    # somewhere doesn't hand over the real secret directly.
    return hmac.new(ACCESS_TOKEN.encode(), b"friday-session-v1", hashlib.sha256).hexdigest()


def session_cookie_value() -> str:
    return _session_value()


def has_valid_session(cookie_value: str) -> bool:
    if not ACCESS_TOKEN:
        return False
    return hmac.compare_digest(cookie_value or "", _session_value())


# Twilio callbacks authenticate with X-Twilio-Signature, not FRIDAY's
# browser/API bearer token. PUBLIC_URL is the canonical external origin;
# never build the signed URL from an untrusted Host/forwarded-host header.
TWILIO_WEBHOOK_PATHS = {
    "/friday/phone/call",
    "/friday/phone/respond",
    "/friday/phone/transcribed",
    "/friday/phone/sms",
}


def is_twilio_webhook(path: str) -> bool:
    return path in TWILIO_WEBHOOK_PATHS


def validate_twilio_webhook(request) -> bool:
    """Validate a Twilio callback before any handler processes it.

    Missing secrets/configuration, malformed URLs, absent signatures, and
    validator errors all fail closed. Query strings are part of Twilio's
    signed callback URL and are therefore included in validation.
    """
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    public_url = os.environ.get("PUBLIC_URL", "").rstrip("/")
    signature = request.headers.get("X-Twilio-Signature", "")
    if not auth_token or not public_url or not signature:
        return False

    from urllib.parse import urlsplit
    parsed = urlsplit(public_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        return False

    try:
        from twilio.request_validator import RequestValidator
        query = request.query_string.decode("ascii")
        signed_url = f"{public_url}{request.path}"
        if query:
            signed_url += f"?{query}"
        return RequestValidator(auth_token).validate(
            signed_url, request.form.to_dict(flat=True), signature
        )
    except Exception:
        return False
