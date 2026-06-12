import os
import requests
from collections import deque

class FridayCore:
    def __init__(self):
        self.api_key = os.environ.get("GEMINI_API_KEY")

        # 🧠 memory (last 10 interactions)
        self.memory = deque(maxlen=10)

        self.system_prompt = (
            "You are F.R.I.D.A.Y., a highly advanced AI assistant. "
            "You are calm, precise, intelligent, and slightly witty. "
            "You respond clearly and efficiently."
        )

    def build_context(self):
        if not self.memory:
            return ""

        return "\n".join(
            [f"User: {m['user']}\nFRIDAY: {m['friday']}" for m in self.memory]
        )

    def think(self, prompt):
        if not self.api_key:
            return "FRIDAY ERROR: Missing Gemini API key."

        try:
            full_prompt = (
                self.system_prompt + "\n\n" +
                self.build_context() +
                f"\nUser: {prompt}"
            )

url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent"
            payload = {
                "contents": [
                    {
                        "parts": [
                            {"text": full_prompt}
                        ]
                    }
                ]
            }

            res = requests.post(
                url,
                params={"key": self.api_key},
                json=payload,
                timeout=15
            )

            data = res.json()

            if "candidates" not in data:
                return f"FRIDAY API ERROR: {data}"

            if not data["candidates"]:
                return "FRIDAY ERROR: Empty response"

            content = data["candidates"][0].get("content", {})
            parts = content.get("parts", [])

            if not parts:
                return "FRIDAY ERROR: No text returned"

            output = parts[0].get("text", "").strip()

        except Exception as e:
            output = f"FRIDAY AI ERROR: {str(e)}"

        self.memory.append({
            "user": prompt,
            "friday": output
        })

        return output
