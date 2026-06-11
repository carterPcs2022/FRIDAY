import os
import requests

class FridayCore:
    def __init__(self):
        self.api_key = os.environ.get("GEMINI_API_KEY")
        self.memory = []

    def think(self, prompt):
        if not self.api_key:
            return "FRIDAY ERROR: No Gemini API key found."

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

            output = data["candidates"][0]["content"]["parts"][0]["text"]

        except Exception as e:
            output = f"FRIDAY AI ERROR: {str(e)}"

        self.memory.append({
            "user": prompt,
            "friday": output
        })

        return output
