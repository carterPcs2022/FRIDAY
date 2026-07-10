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

SPOTIFY_TOKEN_FILE = Path("memory/friday_spotify_token.json")
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "")


class FridaySpotify:

    def _load_token_data(self) -> dict:
        if SPOTIFY_TOKEN_FILE.exists():
            try:
                return json.loads(SPOTIFY_TOKEN_FILE.read_text())
            except Exception:
                return {}
        return {}

    def _save_token_data(self, data: dict):
        SPOTIFY_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        SPOTIFY_TOKEN_FILE.write_text(json.dumps(data, indent=2))

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
                params={"q": query, "type": "track", "limit": 1},
                headers={"Authorization": f"Bearer {token}"},
                timeout=5,
            )
            items = r.json().get("tracks", {}).get("items", [])
            if not items:
                return {"error": f"Can't find {query}"}
            uri = items[0]["uri"]
            name = items[0]["name"]
            artist = items[0]["artists"][0]["name"]
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
        scope = "user-read-playback-state user-modify-playback-state"
        return (
            f"https://accounts.spotify.com/authorize"
            f"?client_id={CLIENT_ID}"
            f"&response_type=code"
            f"&redirect_uri={REDIRECT_URI}"
            f"&scope={scope}"
        )


friday_spotify = FridaySpotify()
