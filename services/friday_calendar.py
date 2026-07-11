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
import time
import json
import httpx
from pathlib import Path
from datetime import datetime, timedelta, timezone

TOKEN_FILE = Path("memory/friday_calendar_token.json")
CLIENT_ID = os.getenv("GOOGLE_CALENDAR_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("GOOGLE_CALENDAR_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv("GOOGLE_CALENDAR_REDIRECT_URI", "")
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
        if TOKEN_FILE.exists():
            try:
                return json.loads(TOKEN_FILE.read_text())
            except Exception:
                return {}
        return {}

    def _save_token(self, data: dict):
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(json.dumps(data, indent=2))

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

    def create_event(self, title: str, start_iso: str, end_iso: str, description: str = "") -> dict:
        token = self._get_access_token()
        if not token:
            return {"error": "Calendar not connected"}
        try:
            r = httpx.post(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                json={
                    "summary": title, "description": description,
                    "start": {"dateTime": start_iso}, "end": {"dateTime": end_iso},
                },
                headers={"Authorization": f"Bearer {token}"},
                timeout=8,
            )
            if r.status_code in (200, 201):
                return {"ok": True, "event": r.json().get("htmlLink", "")}
            return {"error": f"Failed to create event: {r.status_code}"}
        except Exception as e:
            return {"error": str(e)}


friday_calendar = FridayCalendar()
