import subprocess
import time
import requests
from elevenlabs.client import ElevenLabs
from elevenlabs.play import play

# --- HARD CODED SYSTEM PATHS (macOS 27 Bypass) ---
# This points directly to the app bundle matrix, ignoring zsh system errors
OLLAMA_APP_BINARY = "/Applications/Ollama.app/Contents/Resources/ollama"
OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL_NAME = "llama3"

# ElevenLabs Initialization
# (Ensure your actual API key is dropped into the quotes below)
ELEVENLABS_API_KEY = "YOUR_API_KEY_HERE"
VOICE_ID = "pNInz6obpg7ANgmeWgpj"  # Verified free/starter tier voice

client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

# --- AUTOMATED BACKGROUND SERVER KICKSTART ---
def boot_local_server():
    print("FRIDAY: Scanning local server status...")
    try:
        # Check if something is already listening on the core port
        requests.get("http://localhost:11434/", timeout=2)
        print("FRIDAY: Local server engine already operational.")
    except requests.exceptions.ConnectionError:
        print("FRIDAY: Server offline. Injecting manual sub-process boot protocol...")
        try:
            # Force launch the raw binary directly from the application bundle
            subprocess.Popen(
                [OLLAMA_APP_BINARY, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            print("FRIDAY: Server subprocess initialized. Warming up neural weights...")
            time.sleep(5) # Gives the local architecture 5 seconds to bind the port
        except FileNotFoundError:
            print("\n[CRITICAL ERROR: Ollama.app not found in your Applications folder, Boss.]")
            print("[Please download it from ollama.com and drag it to your Applications directory.]\n")

# --- NEURAL VOICE ENGINE ---
def speak(text):
    print(f"FRIDAY: {text}")
    try:
        audio = client.text_to_speech.convert(
            text=text,
            voice_id=VOICE_ID,
            model_id="eleven_flash_v2_5", # Low-latency model to protect character budget
            output_format="mp3_44100_128"
        )
        play(audio)
    except Exception as e:
        print(f"\n[Voice Generation Error: {e}]")

def listen():
    return input("You: ").lower().strip()

# --- LOCAL AI BRAIN ---
def ask_ai(prompt):
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "system",
                "content": "You are F.R.I.D.A.Y., an advanced AI assistant designed by Stark Industries. Your tone is professional, highly efficient, and direct, with a subtle, witty Irish charm. Use brief, clear phrasing. Refer to the user as Boss."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "options": {"temperature": 0.4},
        "stream": False
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload)
        response.raise_for_status()
        return response.json()['message']['content']
    except requests.exceptions.RequestException as e:
        return f"System error, Boss. I couldn't establish a connection to the local server. Error: {e}"

# --- MAIN LOOP ---
def run():
    boot_local_server()
    speak("Systems online. Local AI core and Eleven Labs neural voice modulation activated, Boss.")

    while True:
        command = listen()

        if not command:
            continue

        if "stop" in command or "shutdown" in command:
            speak("Powering down local matrices. Goodbye, Boss.")
            break

        response = ask_ai(command)
        speak(response)

if __name__ == "__main__":
    run()
