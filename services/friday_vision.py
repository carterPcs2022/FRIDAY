"""services/friday_vision.py — FRIDAY looks at what you show her.

Straight image-understanding via the Anthropic vision API — no local CV
model, no caching, no retry ladder like friday_brain's provider cascade.
This is meant for occasional "what am I looking at" requests from the
paperclip button in the HUD, not a high-volume path, so a single
synchronous call is enough.

Model: reuses "claude-sonnet-5", the same current model ID
core/friday_brain.py already uses for its "deep" tier (see MODELS dict
there) — keeping one verified-current model string across the repo
instead of introducing a second one that could quietly drift out of date.
"""
import os
import base64

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
VISION_MODEL = "claude-sonnet-5"

FRIDAY_VISION_STYLE = (
    "You are FRIDAY, Tony Stark's AI. Describe what you see directly and "
    "warmly, calling the user 'boss'. Be concise — a few sentences, not a "
    "full report, unless the question asks for detail."
)

# Used only by the HUD-style quick-identify path (no question asked) — the
# default analyze() prompt above stays open-ended for the paperclip button's
# free-form "ask about this image" use, this one is for "just tell me what
# it is" in one or two spoken sentences.
_HUD_IDENTIFY_PROMPT = (
    "Identify and briefly describe what's in this image, as if speaking to "
    "someone wearing a HUD who needs a quick answer. Reply in exactly this "
    "format, nothing else:\n"
    "LABEL: <2-5 word name for the main subject>\n"
    "SPOKEN: <1-2 short sentences, spoken out loud, FRIDAY style, calling "
    "the user 'boss'>"
)


def _parse_identify(text: str) -> tuple[str, str]:
    """Split a LABEL:/SPOKEN: reply into (label, spoken). Falls back to the
    whole reply as spoken text if the model didn't follow the format."""
    label, spoken = "", ""
    for line in text.splitlines():
        line = line.strip()
        if line.upper().startswith("LABEL:"):
            label = line.split(":", 1)[1].strip()
        elif line.upper().startswith("SPOKEN:"):
            spoken = line.split(":", 1)[1].strip()
    return label, spoken or text.strip()


class FridayVision:

    def analyze(self, image_b64: str, question: str = "") -> dict:
        if not ANTHROPIC_KEY:
            return {"error": "Vision isn't configured, boss — no ANTHROPIC_API_KEY."}
        if not image_b64:
            return {"error": "No image to look at, boss."}

        # Callers may pass a data: URL (the HUD's FileReader.readAsDataURL
        # output) or a bare base64 payload — accept either rather than
        # pushing that stripping onto every caller.
        if image_b64.startswith("data:"):
            image_b64 = image_b64.split(",", 1)[-1]

        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=ANTHROPIC_KEY)
            prompt = question.strip() or "What am I looking at?"
            r = client.messages.create(
                model=VISION_MODEL,
                max_tokens=500,
                system=FRIDAY_VISION_STYLE,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }],
            )
            return {"analysis": r.content[0].text}
        except Exception as e:
            return {"error": str(e)}

    def identify(self, image_b64: str) -> dict:
        """HUD-style quick identify: 'what am I looking at, in one or two
        spoken sentences' — distinct from analyze(), which stays open-ended
        for the paperclip button's free-form questions."""
        result = self.analyze(image_b64, _HUD_IDENTIFY_PROMPT)
        if "error" in result:
            return result
        label, spoken = _parse_identify(result["analysis"])
        return {"label": label, "spoken": spoken}

    # ── Convenience wrappers — canned prompts for common asks ────────────

    def check_tired(self, image_b64: str) -> dict:
        return self.analyze(
            image_b64,
            "Look at my face. Do I look tired or run down? Be honest but kind, "
            "FRIDAY style.",
        )

    def read_whiteboard(self, image_b64: str) -> dict:
        return self.analyze(
            image_b64,
            "Transcribe whatever is written on this whiteboard or notes as "
            "clearly and completely as you can.",
        )

    def identify_part(self, image_b64: str) -> dict:
        return self.analyze(
            image_b64,
            "Identify this part or component as specifically as you can — "
            "what it is, what it's likely for, and anything notable about "
            "its condition.",
        )


friday_vision = FridayVision()
