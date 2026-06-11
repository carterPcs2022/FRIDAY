from elevenlabs.client import ElevenLabs
import subprocess
import tempfile

client = ElevenLabs(
    api_key="sk_d64daf3d9605db468ac854423dd15c8a45d3dc57ea6b6e07"
)

VOICE_ID = "3b8fXc91YHS1i2DYAlBQ"

def speak(text):
    try:
        audio = client.text_to_speech.convert(
            text=text,
            voice_id=VOICE_ID,
            model_id="eleven_multilingual_v2"
        )

        if hasattr(audio, "read"):
            audio_bytes = audio.read()
        else:
            audio_bytes = bytes(audio)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
            f.write(audio_bytes)
            path = f.name

        subprocess.run(["afplay", path])

        print("VOICE: played")

    except Exception as e:
        print("Voice error:", e)
