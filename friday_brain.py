# core.py

import requests
from config import OLLAMA_URL, MODEL, SYSTEM_PROMPT

class FridayCore:
    def __init__(self):
        self.memory = []

    def think(self, user_input):
        prompt = SYSTEM_PROMPT + "\nUser: " + user_input

        try:
            res = requests.post(OLLAMA_URL, json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False
            })

            output = res.json()["response"]

            self.memory.append({
                "user": user_input,
                "friday": output
            })

            return output

        except Exception as e:
            return f"System interruption resolved. Error: {e}"
