"""services/friday_spotify.py — direct Spotify control (no JARVIS proxy
needed). Real OAuth authorization-code flow: the source spec's callback
handler was a literal `pass`, which means SPOTIFY_TOKEN_FILE could never
actually get written and play()/pause() would always fail with "not
authenticated" — implemented the actual code-for-token exchange plus
refresh (access tokens expire in ~1 hour; without refresh this would
work once and then break every hour after)."""
import os
import time
import json
import base64
import httpx
from pathlib import Path
from urllib.parse import urlencode

from db import turso_http_client as turso

SPOTIFY_TOKEN_FILE = Path("memory/friday_spotify_token.json")
SPOTIFY_TOKEN_TABLE = "friday_spotify_token"
SPOTIFY_TOKEN_KEY = "token"
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "")

# Debug visibility into what actually loaded on this deploy — CLIENT_ID/
# REDIRECT_URI printed in full since neither is secret (redirect_uri is
# public in the auth URL itself, client_id is meant to be public per
# OAuth's own model), CLIENT_SECRET masked to length + first/last char
# only, enough to confirm "yes something non-empty loaded" without
# putting the actual secret in Render's log output.
_secret_display = (
    f"{CLIENT_SECRET[0]}...{CLIENT_SECRET[-1]} (len {len(CLIENT_SECRET)})"
    if CLIENT_SECRET else "(empty)"
)
print(
    f"[FRIDAY Spotify] Loaded config — "
    f"CLIENT_ID={CLIENT_ID or '(empty)'} "
    f"CLIENT_SECRET={_secret_display} "
    f"REDIRECT_URI={REDIRECT_URI or '(empty)'}"
)


class FridaySpotify:

    def _load_token_data(self) -> dict:
        if turso.is_configured():
            row, query_ok = None, False
            try:
                turso.ensure_kv_table(SPOTIFY_TOKEN_TABLE)
                row = turso.kv_get(SPOTIFY_TOKEN_TABLE, SPOTIFY_TOKEN_KEY)
                query_ok = True
            except Exception as e:
                print(f"[Turso] Spotify token read failed, falling back to local JSON: {e}")

            if row is not None:
                return row
            if query_ok:
                local = self._read_local_token_data()
                if local:
                    try:
                        turso.kv_set(SPOTIFY_TOKEN_TABLE, SPOTIFY_TOKEN_KEY, local)
                    except Exception as e:
                        print(f"[Turso] Spotify token seed failed: {e}")
                return local

        return self._read_local_token_data()

    def _read_local_token_data(self) -> dict:
        if SPOTIFY_TOKEN_FILE.exists():
            try:
                return json.loads(SPOTIFY_TOKEN_FILE.read_text())
            except Exception:
                return {}
        return {}

    def _save_token_data(self, data: dict):
        SPOTIFY_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        SPOTIFY_TOKEN_FILE.write_text(json.dumps(data, indent=2))

        if turso.is_configured():
            try:
                turso.ensure_kv_table(SPOTIFY_TOKEN_TABLE)
                turso.kv_set(SPOTIFY_TOKEN_TABLE, SPOTIFY_TOKEN_KEY, data)
            except Exception as e:
                print(f"[Turso] Spotify token write failed, local JSON already has it: {e}")

    def _get_token(self) -> str:
        """Returns a valid access token, refreshing it first if expired."""
        data = self._load_token_data()
        if not data.get("access_token"):
            return ""

        if time.time() >= data.get("expires_at", 0):
            refreshed = self._refresh_token(data.get("refresh_token", ""))
            if not refreshed:
                return ""
            return refreshed

        return data["access_token"]

    def _refresh_token(self, refresh_token: str) -> str:
        if not refresh_token or not CLIENT_ID or not CLIENT_SECRET:
            return ""
        try:
            auth = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
            r = httpx.post(
                "https://accounts.spotify.com/api/token",
                data={"grant_type": "refresh_token", "refresh_token": refresh_token},
                headers={"Authorization": f"Basic {auth}"},
                timeout=8,
            )
            if r.status_code != 200:
                return ""
            payload = r.json()
            data = self._load_token_data()
            data["access_token"] = payload["access_token"]
            data["expires_at"] = time.time() + payload.get("expires_in", 3600) - 60
            # Spotify doesn't always return a new refresh_token — keep the
            # old one if it didn't.
            if payload.get("refresh_token"):
                data["refresh_token"] = payload["refresh_token"]
            self._save_token_data(data)
            return data["access_token"]
        except Exception as e:
            print(f"[FRIDAY Spotify] Token refresh failed: {e}")
            return ""

    def exchange_code(self, code: str) -> dict:
        """Called from the /friday/spotify/callback route with the
        authorization code Spotify redirected back with."""
        if not CLIENT_ID or not CLIENT_SECRET or not REDIRECT_URI:
            return {"error": "Spotify not configured"}
        try:
            auth = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
            r = httpx.post(
                "https://accounts.spotify.com/api/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": REDIRECT_URI,
                },
                headers={"Authorization": f"Basic {auth}"},
                timeout=8,
            )
            if r.status_code != 200:
                return {"error": f"Token exchange failed: {r.text[:200]}"}
            payload = r.json()
            self._save_token_data({
                "access_token": payload["access_token"],
                "refresh_token": payload.get("refresh_token", ""),
                "expires_at": time.time() + payload.get("expires_in", 3600) - 60,
            })
            return {"ok": True}
        except Exception as e:
            return {"error": str(e)}

    def _get_devices(self) -> list:
        token = self._get_token()
        if not token:
            return []
        try:
            r = httpx.get(
                "https://api.spotify.com/v1/me/player/devices",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5,
            )
            if r.status_code == 200:
                return r.json().get("devices", [])
        except Exception:
            pass
        return []

    def play(self, query: str = "") -> dict:
        token = self._get_token()
        if not token:
            return {"error": "Spotify not authenticated"}
        devices = self._get_devices()
        if not devices:
            return {"error": "Open Spotify on your phone first, boss."}
        device_id = devices[0]["id"]

        if not query:
            try:
                r = httpx.put(
                    f"https://api.spotify.com/v1/me/player/play?device_id={device_id}",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=5,
                )
                return {"playing": r.status_code in (200, 204)}
            except Exception as e:
                return {"error": str(e)}

        try:
            r = httpx.get(
                "https://api.spotify.com/v1/search",
                params={"q": query, "type": "track", "limit": 10},
                headers={"Authorization": f"Bearer {token}"},
                timeout=5,
            )
            items = r.json().get("tracks", {}).get("items", [])
            if not items:
                return {"error": f"Can't find {query}"}

            # Find best match by comparing track name similarity to the
            # actual query, not just taking Spotify's top-ranked result —
            # Spotify's own relevance ranking factors in popularity, so a
            # cover or remix can rank above the actual song requested.
            query_lower = query.lower().strip()
            best_match = None
            best_score = 0

            for item in items:
                track_name = item["name"].lower()
                if track_name == query_lower:
                    best_match = item
                    break
                if query_lower in track_name or track_name in query_lower:
                    score = len(set(query_lower.split()) & set(track_name.split()))
                    if score > best_score:
                        best_score = score
                        best_match = item

            # Fallback to first result only if nothing scored as a
            # reasonable match.
            selected = best_match or items[0]

            uri = selected["uri"]
            name = selected["name"]
            artist = selected["artists"][0]["name"]
            r2 = httpx.put(
                f"https://api.spotify.com/v1/me/player/play?device_id={device_id}",
                json={"uris": [uri]},
                headers={"Authorization": f"Bearer {token}"},
                timeout=5,
            )
            if r2.status_code in (200, 204):
                return {"playing": True, "track": name, "artist": artist}
            return {"error": f"Playback failed: {r2.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    def pause(self) -> dict:
        token = self._get_token()
        if not token:
            return {"error": "Not authenticated"}
        try:
            r = httpx.put(
                "https://api.spotify.com/v1/me/player/pause",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5,
            )
            return {"paused": r.status_code in (200, 204)}
        except Exception as e:
            return {"error": str(e)}

    def auth_url(self) -> str:
        # Previously built with raw f-string concatenation — the literal
        # space in scope ("...state user-modify...") was going out
        # unencoded in the query string, which is malformed per RFC 3986.
        # urlencode() percent-encodes every value (spaces -> %20, etc.)
        # the way Spotify's authorize endpoint actually expects.
        scope = "user-read-playback-state user-modify-playback-state"
        params = urlencode({
            "client_id": CLIENT_ID,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": scope,
        })
        print(f"[FRIDAY Spotify] auth_url scope requested: {scope}")
        return f"https://accounts.spotify.com/authorize?{params}"


friday_spotify = FridaySpotify()
