"""services/friday_voice.py — FRIDAY's voice. Distinct from JARVIS: warmer,
faster ElevenLabs voice, with an edge-tts (Irish accent) fallback if
ElevenLabs is unavailable or unconfigured.

Every generation gets a unique timestamped filename — never overwrite a
fixed path — so a client fetching by filename+cache-bust query param never
gets a stale cached clip from a previous response.
"""
import os
import re
import time
from pathlib import Path

import httpx

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

# Sarah — warm, conversational. Distinct from JARVIS's deep/formal voice.
FRIDAY_VOICE_ID = os.getenv("FRIDAY_VOICE_ID", "eQ3MKh19cr7ApgSW5Ob0")
ELEVENLABS_KEY = os.getenv("ELEVENLABS_API_KEY", "")

VOICE_SETTINGS = {
    "normal":   {"stability": 0.5, "similarity_boost": 0.8},
    "focused":  {"stability": 0.7, "similarity_boost": 0.8},
    "support":  {"stability": 0.4, "similarity_boost": 0.9},
    "coverage": {"stability": 0.6, "similarity_boost": 0.8},
    "brief":    {"stability": 0.6, "similarity_boost": 0.7},
    "night":    {"stability": 0.6, "similarity_boost": 0.8},
}


def _clean(text: str) -> str:
    text = re.sub(r"\[.*?\]", "", text or "")
    text = re.sub(r"[*_`#]", "", text)
    # friday_brain.think() calls regularly run at max_tokens=600-800 (see
    # core/friday_brain.py), which is 2000+ characters of English — the
    # old 400-char cap here silently chopped every such reply off mid-
    # sentence before it ever reached TTS. This is what "she cuts herself
    # off" actually was. 2000 covers a normal-length reply with room to
    # spare while still bounding TTS cost/latency for a genuine outlier.
    return text.strip()[:2000]


def speak(text: str, mode: str = "normal") -> str | None:
    """Generate FRIDAY's voice for `text`. Returns a relative filename
    (e.g. "friday_voice_1234.mp3") under static/, or None if both
    ElevenLabs and the edge-tts fallback fail — never raises."""
    clean = _clean(text)
    if not clean:
        return None

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    ts = int(time.time() * 1000)
    filename = f"friday_voice_{ts}.mp3"
    out_path = STATIC_DIR / filename

    if ELEVENLABS_KEY:
        settings = VOICE_SETTINGS.get(mode, VOICE_SETTINGS["normal"])
        try:
            r = httpx.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{FRIDAY_VOICE_ID}",
                json={
                    "text": clean,
                    "model_id": "eleven_turbo_v2",
                    "voice_settings": settings,
                },
                headers={"xi-api-key": ELEVENLABS_KEY, "Content-Type": "application/json"},
                timeout=20,  # was 10 — too tight now that _clean() allows up to 2000 chars through
            )
            if r.status_code == 200:
                out_path.write_bytes(r.content)
                return filename
            print(f"[FRIDAY Voice] ElevenLabs returned {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"[FRIDAY Voice] ElevenLabs failed: {e}")

    try:
        import asyncio
        import edge_tts

        async def _edge():
            comm = edge_tts.Communicate(clean, "en-IE-EmilyNeural")
            await comm.save(str(out_path))

        asyncio.run(_edge())
        if out_path.exists() and out_path.stat().st_size > 0:
            return filename
    except Exception as e:
        print(f"[FRIDAY Voice] edge-tts fallback failed: {e}")

    return None
