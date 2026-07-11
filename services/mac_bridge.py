"""services/mac_bridge.py — thin client for the app-open subset of Mac
Bridge's routes. The HomeKit/Shortcuts path in server.py already talks to
Mac Bridge inline for shortcut dispatch; this gives command() a reusable
helper for the separate /mac/open endpoint instead of a third inline
httpx block.
"""
import os
import httpx

MAC_URL = os.getenv("MAC_BRIDGE_URL", "")
MAC_TOKEN = os.getenv("MAC_BRIDGE_TOKEN", "")


class MacBridge:

    def _call(self, endpoint: str, data: dict = {}) -> dict:
        if not MAC_URL:
            return {"error": "not configured"}
        try:
            r = httpx.post(
                f"{MAC_URL}/mac/{endpoint}",
                json={**data, "token": MAC_TOKEN}, timeout=8,
            )
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    def open_app(self, app_name: str) -> dict:
        return self._call("open", {"app": app_name})


mac_bridge = MacBridge()
