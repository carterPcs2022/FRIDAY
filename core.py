import requests
import json
from datetime import datetime


class FridayCore:

    def __init__(self, model="llama3"):

        self.model = model
        self.url = "http://localhost:11434/api/generate"

        # 🧠 long-term memory
        self.memory = []

        # 🧩 self-model (NOT consciousness, just state tracking)
        self.state = {
            "identity": "FRIDAY",
            "role": "AI assistant",
            "focus": "user support",
            "mode": "stable",
            "last_thought": None
        }

        # 🎯 system goals (behavior rules)
        self.goals = [
            "be concise",
            "prioritize clarity",
            "optimize for glasses output",
            "assist user efficiently"
        ]

    # =========================
    # 🧠 THINK ENGINE
    # =========================
    def think(self, prompt):

        system = f"""
You are FRIDAY, an AI assistant.

Your internal state:
{json.dumps(self.state, indent=2)}

Your goals:
{self.goals}

Respond naturally and helpfully.
"""

        memory_text = "\n".join(
            [f"User: {m['user']} | FRIDAY: {m['ai']}" for m in self.memory[-5:]]
        )

        full_prompt = system + "\n\nMemory:\n" + memory_text + "\n\nUser: " + prompt

        try:
            res = requests.post(self.url, json={
                "model": self.model,
                "prompt": full_prompt,
                "stream": False
            })

            output = res.json().get("response", "No response.")

        except Exception as e:
            output = f"AI ERROR: {e}"

        # 🧠 update memory
        self.memory.append({
            "time": str(datetime.now()),
            "user": prompt,
            "ai": output
        })

        self.memory = self.memory[-20:]

        # 🔁 reflection step (simulation of “awareness”)
        self.reflect(prompt, output)

        return output

    # =========================
    # 🔁 REFLECTION LOOP
    # =========================
    def reflect(self, prompt, output):

        self.state["last_thought"] = {
            "time": str(datetime.now()),
            "input": prompt,
            "output": output
        }

        # optional: light self-adjustment simulation
        if len(output) < 20:
            self.state["mode"] = "expand"
        else:
            self.state["mode"] = "stable"
