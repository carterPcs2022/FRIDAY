import os
import requests

class FridayCore:
    def __init__(self):
        self.api_key = os.environ.get("GEMINI_API_KEY")
        self.memory = []

    def think(self, prompt):
        if not self.api_key:
            return "FRIDAY ERROR: Missing Gemini API key."

        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.api_key}"

            payload = {
                "contents": [
                    {
                        "parts": [
                            {"text": prompt}
                        ]
                    }
                ]
            }

            res = requests.post(url, json=payload, timeout=15)
            data = res.json()

            if "candidates" not in data:
                return f"FRIDAY API ERROR: {data}"

            if not data["candidates"]:
                return "FRIDAY ERROR: Empty response from Gemini"

            content = data["candidates"][0].get("content", {})
            parts = content.get("parts", [])

            if not parts:
                return "FRIDAY ERROR: No response text returned"

            output = parts[0].get("text", "")

        except Exception as e:
            output = f"FRIDAY AI ERROR: {str(e)}"

        self.memory.append({
            "user": prompt,
            "friday": output
        })

        return output
