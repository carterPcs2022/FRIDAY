"""services/friday_translate.py — text translation over
friday_brain.think(), speaks the result if voice is available."""
import re
import json


class FridayTranslator:

    def translate(self, text: str, target_lang: str = "English") -> dict:
        from core.friday_brain import friday_brain

        result = friday_brain.think(
            f"Translate to {target_lang}:\n{text}\n\n"
            f"Reply as JSON: {{translation, source_language, notes}}"
        )["response"]

        try:
            clean = re.sub(r"```json|```", "", result).strip()
            data = json.loads(clean)
        except Exception:
            data = {"translation": result, "source_language": "unknown"}

        translation = data.get("translation", "")
        try:
            from services.friday_voice import speak
            speak(translation)
        except Exception:
            pass

        return {
            "original": text, "translation": translation,
            "source": data.get("source_language", ""), "target": target_lang,
        }


translator = FridayTranslator()
