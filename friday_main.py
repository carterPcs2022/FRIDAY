import time
import traceback
from friday_core import FridayCore
from elevenlabs.client import ElevenLabs
from elevenlabs import play

# ---------- AI CORE ----------
ai = FridayCore()

# ---------- ELEVENLABS ----------
client = ElevenLabs()
VOICE_ID = "3b8fXc91YHS1i2DYAlBQ"


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
        print("Voice error:", e)


def safe_think(prompt):
    try:
        return ai.think(prompt)
    except Exception as e:
        return f"System error recovered: {e}"


def main_loop():
    print("F.R.I.D.A.Y. online.")

    while True:
        try:
            user_input = input("You: ")

            if user_input.lower() in ["exit", "quit"]:
                speak("Shutting down.")
                break

            response = safe_think(user_input)

            print("FRIDAY:", response)
            speak(response)

        except KeyboardInterrupt:
            print("\nManual shutdown detected.")
            break

        except Exception as e:
            print("Recovered from error:", e)
            traceback.print_exc()
            time.sleep(1)


# ---------- AUTO-RECOVERY WRAPPER ----------
if __name__ == "__main__":
    while True:
        try:
            main_loop()
        except Exception as e:
            print("CRITICAL FAILURE RECOVERED:", e)
            time.sleep(2)
