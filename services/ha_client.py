"""services/ha_client.py — thin client for Home Assistant's REST API.

HA only runs locally (Docker on the boss's Mac) — reachable while the Mac
is awake and the container is running, never guaranteed otherwise. Every
call swallows its own errors and returns an "unavailable" signal instead
of raising, same convention as services/mac_bridge.py.
"""
import os
import logging
import httpx

HA_URL = os.getenv("HA_URL", "")
HA_TOKEN = os.getenv("HA_TOKEN", "")
TIMEOUT = 5


class HomeAssistant:

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {HA_TOKEN}",
            "Content-Type": "application/json",
        }

    def get_states(self) -> dict:
        if not HA_URL:
            return {"error": "not configured"}
        try:
            r = httpx.get(f"{HA_URL}/api/states", headers=self._headers(), timeout=TIMEOUT)
            r.raise_for_status()
            return {"states": r.json()}
        except Exception as e:
            logging.warning(f"HA get_states failed: {e}")
            return {"error": str(e)}

    def get_state(self, entity_id: str) -> dict:
        if not HA_URL:
            return {"error": "not configured"}
        try:
            r = httpx.get(f"{HA_URL}/api/states/{entity_id}", headers=self._headers(), timeout=TIMEOUT)
            r.raise_for_status()
            return {"state": r.json()}
        except Exception as e:
            logging.warning(f"HA get_state({entity_id}) failed: {e}")
            return {"error": str(e)}

    def call_service(self, domain: str, service: str, entity_id: str) -> dict:
        if not HA_URL:
            return {"error": "not configured"}
        try:
            r = httpx.post(
                f"{HA_URL}/api/services/{domain}/{service}",
                headers=self._headers(), json={"entity_id": entity_id}, timeout=TIMEOUT,
            )
            r.raise_for_status()
            return {"result": r.json()}
        except Exception as e:
            logging.warning(f"HA call_service({domain}.{service}, {entity_id}) failed: {e}")
            return {"error": str(e)}


home_assistant = HomeAssistant()


if __name__ == "__main__":
    # Smoke test: confirm HA is reachable locally and returns real entities.
    try:
        from dotenv import load_dotenv
        load_dotenv()
        HA_URL = os.getenv("HA_URL", "")
        HA_TOKEN = os.getenv("HA_TOKEN", "")
    except ImportError:
        pass

    result = home_assistant.get_states()
    if "error" in result:
        print(f"FAILED: {result['error']}")
    else:
        states = result["states"]
        print(f"OK: {len(states)} entities")
        for s in states[:10]:
            print(f"  {s['entity_id']}: {s['state']}")
