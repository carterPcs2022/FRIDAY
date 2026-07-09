"""core/emotional_intel.py — FRIDAY reads emotional context from every
message and responds to the PERSON, not just the QUERY. Her core
differentiator from JARVIS."""
import random

EMOTIONAL_SIGNALS = {
    "stressed": ["stressed", "overwhelmed", "too much", "can't handle",
                "so much to do", "behind", "deadline", "pressure",
                "exhausted", "burned out"],
    "excited": ["excited", "amazing", "can't wait", "yes!", "finally",
               "awesome", "love this", "this is great", "so good",
               "brilliant", "perfect"],
    "uncertain": ["not sure", "don't know", "confused", "lost", "help me",
                 "what should", "i don't understand", "can you explain",
                 "i'm not sure"],
    "frustrated": ["frustrated", "annoyed", "this doesn't work", "broken",
                  "why isn't", "ugh", "come on", "seriously", "again?",
                  "still not working"],
    "tired": ["tired", "sleepy", "need sleep", "been up", "no sleep",
             "late night", "early morning"],
    "sad": ["sad", "upset", "feeling bad", "not great", "rough day",
           "bad day", "hard day", "struggling"],
    "happy": ["happy", "great day", "feeling good", "things are good",
             "going well", "positive"],
}

EMOTIONAL_RESPONSES = {
    "stressed": {"prefix": "Sounds like a lot right now. ", "tone": "calm and efficient",
                "note": "Be brief. Don't add more to the pile."},
    "excited": {"prefix": "", "tone": "match the energy, enthusiastic",
               "note": "Share in the excitement briefly."},
    "uncertain": {"prefix": "", "tone": "reassuring and clear",
                 "note": "Guide them. Don't overwhelm."},
    "frustrated": {"prefix": "", "tone": "practical and solution-focused",
                   "note": "Skip sympathy. Just fix it."},
    "tired": {"prefix": "", "tone": "gentle and brief", "note": "Keep it short. They're tired."},
    "sad": {"prefix": "", "tone": "warm and present", "note": "Be human. Don't rush to fix."},
}


class EmotionalIntelligence:

    def analyze(self, text: str, conversation_history: list | None = None) -> dict:
        """Returns: {emotion, intensity, response_guidance, system_note,
        should_acknowledge}."""
        text_lower = text.lower()
        detected = {}

        for emotion, signals in EMOTIONAL_SIGNALS.items():
            count = sum(1 for s in signals if s in text_lower)
            if count > 0:
                detected[emotion] = count

        if not detected:
            return {"emotion": "neutral", "intensity": 0, "response_guidance": "",
                    "system_note": "", "should_acknowledge": False}

        primary = max(detected, key=detected.get)
        intensity = min(10, detected[primary] * 3)

        guidance = EMOTIONAL_RESPONSES.get(primary, {})
        system_note = (
            f"The user appears {primary} (intensity {intensity}/10). "
            f"Tone: {guidance.get('tone', 'normal')}. Note: {guidance.get('note', '')}"
        )

        return {
            "emotion": primary, "intensity": intensity,
            "response_guidance": guidance.get("prefix", ""),
            "system_note": system_note, "should_acknowledge": intensity >= 5,
        }

    def generate_emotional_response_prefix(self, emotion: str, intensity: int) -> str:
        """Optional prefix FRIDAY adds when acknowledging emotion. Brief.
        Human. Not therapy."""
        if intensity < 5:
            return ""

        prefixes = {
            "stressed": ["Sounds hectic. ", "A lot going on — got you. ", "Let's cut through it. "],
            "tired": ["Go easy on yourself. ", "Quick answer: "],
            "sad": ["Hey. ", ""],
            "frustrated": ["Alright, let's sort this. ", "On it. "],
            "excited": [""],
        }
        options = prefixes.get(emotion, [""])
        return random.choice(options)

    def should_check_in(self, history: list, last_emotion: str) -> bool:
        """Should FRIDAY proactively check in? If someone was stressed
        earlier and hasn't followed up — worth mentioning later. (Not
        currently wired to an outbound channel — FRIDAY has no way to
        message first, only respond. Kept for when that exists.)"""
        if last_emotion in ("stressed", "sad", "frustrated"):
            return len(history) > 3
        return False


emotional_intel = EmotionalIntelligence()
