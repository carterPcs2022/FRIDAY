# voice.py

from elevenlabs.client import ElevenLabs
from elevenlabs import play
from config import VOICE_ID

client = ElevenLabs()

def speak(text):
    try:
        audio = client.text_to_speech.convert(
            text=text,
            voice_id=VOICE_ID,
            model_id="eleven_multilingual_v2",
            voice_settings={
                "stability": 0.75,
                "similarity_boost": 0.65,
                "style": 0.2,
                "use_speaker_boost": True
            }
        )
        play(audio)

    except Exception as e:
        print("Voice system error:", e)
