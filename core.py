import os
import requests
from collections import deque
import datetime


class FridayCore:
    """
    FRIDAY FINAL CORE SYSTEM
    - AI reasoning layer
    - device command layer ready
    - fallback safe mode
    - memory enabled
    """

    def __init__(self):
        self.api_key = os.environ.get("GEMINI_API_KEY")

        # short-term memory (lightweight + stable)
        self.memory = deque(maxlen=20)

        # system personality
        self.system_prompt = (
            "You are F.R.I.D.A.Y., an advanced AI assistant system. "
            "You are precise, calm, and highly intelligent. "
            "You can interpret commands and respond clearly. "
            "You are part of a device-control ecosystem."
        )

        # SAFE fallback responses (prevents API failure dead-ends)
        self.fallbacks = {
            "status": "All systems operational.",
            "hello": "FRIDAY online.",
            "time": lambda: str(datetime.datetime.now())
        }

    # ----------------------------
    # MEMORY BUILDER
    # ----------------------------
    def build_context(self):
        if not self.memory:
            return ""

        return "\n".join(
            [f"User: {m['user']}\nFRIDAY: {m['friday']}" for m in self.memory]
        )

    # ----------------------------
    # FAST LOCAL RESPONSES
    # ----------------------------
    def fast_reply(self, prompt: str):
        p = prompt.lower().strip()

        if "status" in p:
            return self.fallbacks["status"]

        if "hello" in p or "hey" in p:
            return self.fallbacks["hello"]

        if "time" in p:
            return self.fallbacks["time"]()

        return None

    # ----------------------------
    # GEMINI CALL (PRIMARY BRAIN)
    # ----------------------------
def call_gemini(self, prompt: str):
    if not self.api_key:
        return self.fallback_ai(prompt)

    MODEL = "gemini-3.1-flash-lite"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

    payload = {
        "contents": [
            {"parts": [{"text": prompt}]}
        ]
    }

    try:
        res = requests.post(
            url,
            params={"key": self.api_key},
            json=payload,
            timeout=10
        )

        data = res.json()

        # 🧠 HARD SAFETY CHECKS
        if "error" in data:
            return self.fallback_ai(prompt)

        if "candidates" not in data or not data["candidates"]:
            return self.fallback_ai(prompt)

        content = data["candidates"][0].get("content", {})
        parts = content.get("parts", [])

        if not parts:
            return self.fallback_ai(prompt)

        return parts[0].get("text", "FRIDAY: Empty response received.")

    except Exception:
        return self.fallback_ai(prompt)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

        if not OPENAI_API_KEY:
            return "FRIDAY is running in offline mode. Primary systems unavailable."

        url = "https://api.openai.com/v1/chat/completions"

        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "You are FRIDAY, a precise AI assistant."},
                {"role": "user", "content": prompt}
            ]
        }

        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }

        res = requests.post(url, json=payload, headers=headers, timeout=10)
        data = res.json()

        return data["choices"][0]["message"]["content"]

if res.status_code != 200:
    return "FRIDAY fallback failed: OpenAI API error."

    except Exception:
        return "FRIDAY OFFLINE MODE: All AI systems are currently unavailable."
