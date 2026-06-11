from elevenlabs.client import ElevenLabs

client = ElevenLabs(api_key="sk_d64daf3d9605db468ac854423dd15c8a45d3dc57ea6b6e07")

VOICE_ID = "3b8fXc91YHS1i2DYAlBQ"

def speak(text):
    print("STEP 1: entered speak()")

    audio_stream = client.text_to_speech.convert(
        text=text,
        voice_id=VOICE_ID,
        model_id="eleven_multilingual_v2"
    )

    print("STEP 2: got stream:", type(audio_stream))

    chunks = []
    for i, chunk in enumerate(audio_stream):
        print("STEP 3: chunk", i)
        chunks.append(chunk)
        if i > 5:
            break

    print("STEP 4: collected chunks:", len(chunks))
