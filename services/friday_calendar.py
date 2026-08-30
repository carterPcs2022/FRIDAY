"""services/friday_calendar.py — Google Calendar via OAuth2 web flow.

Google doesn't support app-password auth for Calendar (unlike Gmail's
IMAP/SMTP) — OAuth is unavoidable here. Uses the same web
authorization-code flow as services/friday_spotify.py (redirect ->
consent screen -> callback route exchanges the code), not the desktop
"open a local browser" flow core/tools/gmail.py used to use — that flow
needs a browser on the same machine running the code, which doesn't
exist on a headless Render server.

First-time setup:
  1. console.cloud.google.com -> new project -> enable Google Calendar API.
  2. OAuth consent screen -> External -> add your own account as a test user.
  3. Credentials -> Create OAuth client ID -> Web application.
     Authorized redirect URI: https://<your-app>.onrender.com/friday/calendar/callback
  4. Set env vars: GOOGLE_CALENDAR_CLIENT_ID, GOOGLE_CALENDAR_CLIENT_SECRET,
     GOOGLE_CALENDAR_REDIRECT_URI (the same URL as step 3).
  5. Visit /friday/calendar/auth once, sign in, approve — token is saved
     from there on (refreshed automatically).
"""
import os
import re
import time
import json
import httpx
from pathlib import Path
from datetime import datetime, timedelta, timezone

from db import turso_http_client as turso

TOKEN_FILE = Path("memory/friday_calendar_token.json")
# Mirrored to Turso as well -- see _load_token() for why the local file
# alone isn't enough on this deploy.
TOKEN_TABLE = "calendar_token"
TOKEN_KEY = "oauth"
# .strip() is load-bearing, not tidiness: pasting a value into a hosting
# dashboard's env-var field very easily picks up a trailing newline, and
# REDIRECT_URI goes straight into a Location header via redirect(), where
# Werkzeug rejects newlines outright ("Header values must not contain
# newline characters") as header-injection protection. Confirmed live --
# that raised on /friday/calendar/auth and surfaced only as the generic
# "Something went wrong, boss.", with the real cause buried in the logs.
CLIENT_ID = os.getenv("GOOGLE_CALENDAR_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("GOOGLE_CALENDAR_CLIENT_SECRET", "").strip()
REDIRECT_URI = os.getenv("GOOGLE_CALENDAR_REDIRECT_URI", "").strip()
SCOPE = "https://www.googleapis.com/auth/calendar"


class FridayCalendar:

    def is_configured(self) -> bool:
        return bool(CLIENT_ID and CLIENT_SECRET and REDIRECT_URI)

    def is_connected(self) -> bool:
        """Distinct from is_configured(): configured means the app has
        credentials to attempt OAuth; connected means the user has
        actually completed it and a token exists."""
        return self.is_configured() and bool(self._load_token().get("refresh_token"))

    def _load_token(self) -> dict:
        """Turso first, local JSON as the fallback -- same pattern as
        services/friday_gmail.py's send token and services/friday_habits.py,
        and for the same reason: render.yaml mounts no disk, so memory/ is
        ephemeral. A token kept only on local disk is lost on every
        redeploy *and* every free-tier idle spin-down, which would mean
        re-running the consent flow every time FRIDAY wakes up. The
        refresh token is the one piece of state here that genuinely has
        to outlive the container."""
        if turso.is_configured():
            try:
                turso.ensure_kv_table(TOKEN_TABLE)
                row = turso.kv_get(TOKEN_TABLE, TOKEN_KEY)
                if row:
                    return row
            except Exception as e:
                print(f"[Turso] calendar token read failed, falling back to local JSON: {e}")
        return self._read_local_token()

    def _read_local_token(self) -> dict:
        if TOKEN_FILE.exists():
            try:
                return json.loads(TOKEN_FILE.read_text())
            except Exception:
                return {}
        return {}

    def _save_token(self, data: dict):
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(json.dumps(data, indent=2))

        if turso.is_configured():
            try:
                turso.ensure_kv_table(TOKEN_TABLE)
                turso.kv_set(TOKEN_TABLE, TOKEN_KEY, data)
            except Exception as e:
                print(f"[Turso] calendar token write failed, local JSON already has it: {e}")

    def _get_access_token(self) -> str:
        data = self._load_token()
        if not data.get("access_token"):
            return ""
        if time.time() >= data.get("expires_at", 0):
            return self._refresh(data.get("refresh_token", ""))
        return data["access_token"]

    def _refresh(self, refresh_token: str) -> str:
        if not refresh_token or not self.is_configured():
            return ""
        try:
            r = httpx.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                    "refresh_token": refresh_token, "grant_type": "refresh_token",
                },
                timeout=8,
            )
            if r.status_code != 200:
                return ""
            payload = r.json()
            data = self._load_token()
            data["access_token"] = payload["access_token"]
            data["expires_at"] = time.time() + payload.get("expires_in", 3600) - 60
            self._save_token(data)
            return data["access_token"]
        except Exception as e:
            print(f"[FRIDAY Calendar] Token refresh failed: {e}")
            return ""

    def auth_url(self) -> str:
        return (
            "https://accounts.google.com/o/oauth2/v2/auth"
            f"?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
            f"&response_type=code&scope={SCOPE}"
            "&access_type=offline&prompt=consent"
        )

    def exchange_code(self, code: str) -> dict:
        if not self.is_configured():
            return {"error": "Calendar not configured"}
        try:
            r = httpx.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                    "code": code, "redirect_uri": REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
                timeout=8,
            )
            if r.status_code != 200:
                return {"error": f"Token exchange failed: {r.text[:200]}"}
            payload = r.json()
            self._save_token({
                "access_token": payload["access_token"],
                "refresh_token": payload.get("refresh_token", ""),
                "expires_at": time.time() + payload.get("expires_in", 3600) - 60,
            })
            return {"ok": True}
        except Exception as e:
            return {"error": str(e)}

    def _events(self, time_min: str, time_max: str, max_results: int = 10) -> list:
        token = self._get_access_token()
        if not token:
            return []
        try:
            r = httpx.get(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                params={
                    "timeMin": time_min, "timeMax": time_max,
                    "maxResults": max_results, "singleEvents": "true", "orderBy": "startTime",
                },
                headers={"Authorization": f"Bearer {token}"},
                timeout=8,
            )
            if r.status_code != 200:
                return []
            items = r.json().get("items", [])
            events = []
            for item in items:
                start = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date", "")
                events.append({
                    "id": item.get("id", ""), "title": item.get("summary", "(no title)"),
                    "start": start, "location": item.get("location", ""),
                    # Google's events.list already returns this on the raw
                    # item when the event has invitees — just wasn't being
                    # surfaced here before. Empty for solo blocked-off time.
                    "attendees": item.get("attendees", []),
                })
            return events
        except Exception as e:
            print(f"[FRIDAY Calendar] {e}")
            return []

    def get_today(self) -> list:
        now = datetime.now(timezone.utc)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)
        return self._events(start_of_day.isoformat(), end_of_day.isoformat())

    def get_upcoming(self, hours: int = 24) -> list:
        now = datetime.now(timezone.utc)
        return self._events(now.isoformat(), (now + timedelta(hours=hours)).isoformat())

    @staticmethod
    def _is_date_only(value: str) -> bool:
        return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", (value or "").strip()))

    def _event_times(self, start_iso: str, end_iso: str) -> tuple[dict, dict]:
        """Google's API takes {"date": ...} for an all-day event and
        {"dateTime": ...} for a timed one -- passing a bare date as
        dateTime is rejected. Picks the field from the value's own shape,
        so callers just pass "2026-09-01" for all-day and a full
        "2026-09-01T15:00:00" for timed, with no extra flag to keep in
        sync.

        end.date is *exclusive* in Google's model: a single-day event on
        the 1st has to be sent as end 2026-09-02, or it lands zero-length
        and shows up wrong in the UI. This takes the inclusive last day
        (how people actually describe dates -- "the 1st", "the 1st to the
        3rd") and does that conversion here, so the quirk lives next to
        the API call rather than leaking into every caller."""
        if self._is_date_only(start_iso) and self._is_date_only(end_iso):
            last_day = datetime.strptime(end_iso.strip(), "%Y-%m-%d").date()
            exclusive_end = last_day + timedelta(days=1)
            return {"date": start_iso.strip()}, {"date": exclusive_end.isoformat()}
        return {"dateTime": start_iso}, {"dateTime": end_iso}

    def create_event(self, title: str, start_iso: str, end_iso: str, description: str = "") -> dict:
        token = self._get_access_token()
        if not token:
            return {"error": "Calendar not connected"}
        start_field, end_field = self._event_times(start_iso, end_iso)
        try:
            r = httpx.post(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                json={
                    "summary": title, "description": description,
                    "start": start_field, "end": end_field,
                },
                headers={"Authorization": f"Bearer {token}"},
                timeout=8,
            )
            if r.status_code in (200, 201):
                body = r.json() or {}
                # The event id was discarded and only htmlLink kept. The
                # id is what lets core/outcome_verify.py read the event
                # back and confirm it exists, rather than trusting a 200.
                return {"ok": True, "event": body.get("htmlLink", ""),
                        "event_id": body.get("id", "")}
            return {"error": f"Failed to create event: {r.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    def event_exists(self, event_id: str) -> dict:
        """Read an event back by id. Same three states as
        FridayGmail.message_exists, for the same reason."""
        if not event_id:
            return {"state": "unknown", "detail": "no event id was returned"}
        token = self._get_access_token()
        if not token:
            return {"state": "unknown", "detail": "calendar not connected"}
        try:
            r = httpx.get(
                f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{event_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=8,
            )
        except Exception as e:
            return {"state": "unknown", "detail": f"couldn't reach Calendar: {e}"}

        if r.status_code == 404:
            return {"state": "contradicted", "detail": "no such event on the calendar"}
        if r.status_code != 200:
            return {"state": "unknown", "detail": f"Calendar returned {r.status_code}"}
        try:
            status = (r.json() or {}).get("status", "")
        except Exception:
            return {"state": "unknown", "detail": "unreadable Calendar response"}
        if status == "cancelled":
            return {"state": "contradicted", "detail": "the event is cancelled"}
        return {"state": "confirmed", "detail": event_id}


# The Google backend is always instantiated -- the OAuth routes
# (routes/spotify_calendar.py) reference it explicitly, since the
# redirect/callback flow is Google-specific.
friday_google_calendar = FridayCalendar()


def _select_backend():
    """Pick the active calendar backend. FRIDAY_CALENDAR_BACKEND forces it
    ("apple"/"google"); the default "auto" prefers Apple when it's
    configured, since that's the calendar the boss actually uses, and
    falls back to Google otherwise. Every consumer imports `friday_calendar`
    (this name) from here or via core/app_state, so selecting once here is
    all it takes -- no call site changes."""
    pref = os.getenv("FRIDAY_CALENDAR_BACKEND", "auto").strip().lower()
    try:
        from services.friday_apple_calendar import friday_apple_calendar
    except Exception as e:
        print(f"[FRIDAY Calendar] Apple backend unavailable: {e}")
        friday_apple_calendar = None

    if pref == "google":
        return friday_google_calendar
    if pref == "apple":
        return friday_apple_calendar or friday_google_calendar
    # auto
    if friday_apple_calendar and friday_apple_calendar.is_configured():
        return friday_apple_calendar
    return friday_google_calendar


friday_calendar = _select_backend()
