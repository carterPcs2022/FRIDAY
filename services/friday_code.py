"""services/friday_code.py — quick code review/fix/explain over
friday_brain.think()."""


class FridayCodeIntel:

    def quick_review(self, code: str, language: str = "") -> dict:
        from core.friday_brain import friday_brain

        result = friday_brain.think(
            f"Quick code review ({language or 'detect language'}):\n```\n{code[:2000]}\n```\n\n"
            f"Bugs, quick wins, one thing to fix NOW. Fast. Actionable."
        )
        return {"review": result["response"]}

    def fix(self, code: str, error: str = "") -> dict:
        from core.friday_brain import friday_brain

        result = friday_brain.think(
            f"Fix this code:\n```\n{code[:2000]}\n```\nError: {error}\n\nFixed code + explanation."
        )
        return {"fixed": result["response"]}

    def explain(self, code: str) -> dict:
        from core.friday_brain import friday_brain

        result = friday_brain.think(
            f"Explain in plain English:\n```\n{code[:2000]}\n```\nWhat it does, what could break."
        )
        return {"explanation": result["response"]}


friday_code = FridayCodeIntel()
