"""services/voice_transcribe.py — speech-to-text for the HUD's hands-free
wake-word flow, via Groq's hosted Whisper endpoint.

Groq (not OpenAI) because it's already the fast/cheap inference provider
this repo leans on elsewhere for text — using it here too avoids a second
STT vendor and a second API key just for transcription. whisper-large-v3-turbo
is Groq's fastest Whisper variant, which matters for a "listening while you
talk" UX where multi-second latency would feel broken.
"""
import os

import httpx

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


def transcribe_audio(audio_bytes: bytes, filename: str = "audio.webm") -> dict:
    """Send a captured command clip to Groq Whisper. Returns {"text": ...}
    on success or {"text": "", "error": ...} on any failure — callers treat
    an empty text as "nothing usable heard" rather than a hard error."""
    if not GROQ_API_KEY:
        return {"text": "", "error": "GROQ_API_KEY not configured"}
    if not audio_bytes:
        return {"text": "", "error": "no audio received"}

    try:
        r = httpx.post(
            TRANSCRIBE_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            files={"file": (filename, audio_bytes, "application/octet-stream")},
            data={"model": "whisper-large-v3-turbo"},
            timeout=20,
        )
        if r.status_code != 200:
            return {"text": "", "error": f"Transcription failed: {r.status_code} {r.text[:200]}"}
        return {"text": r.json().get("text", "").strip()}
    except Exception as e:
        return {"text": "", "error": str(e)}
