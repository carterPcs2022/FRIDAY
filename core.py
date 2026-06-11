import requests

class FridayCore:
    def __init__(self, model="llama3"):
        self.model = model

        # IMPORTANT:
        # localhost will NOT work in Cloud Run
        # so we make this safe + fallback-ready
        self.url = None

        self.memory = []

    def think(self, prompt):
        """
        Cloud-safe FRIDAY brain.
        Falls back gracefully if no local AI server exists.
        """

        system_style = (
            "You are F.R.I.D.A.Y., a highly intelligent, calm, slightly witty AI assistant. "
            "You respond concisely and logically."
        )

        full_prompt = system_style + "\n\nUser: " + prompt

        # ----------------------------
        # OPTION 1: If cloud AI exists later
        # ----------------------------
        if self.url:
            try:
                payload = {
                    "model": self.model,
                    "prompt": full_prompt,
                    "stream": False
                }

                res = requests.post(self.url, json=payload, timeout=10)
                output = res.json().get("response", "No response")

            except Exception as e:
                output = f"AI cloud error: {str(e)}"

        # ----------------------------
        # OPTION 2: SAFE FALLBACK (CURRENT)
        # ----------------------------
        else:
            output = f"FRIDAY (offline brain): {prompt}"

        # Memory system (simple version for now)
        self.memory.append({
            "user": prompt,
            "friday": output
        })

        return output
