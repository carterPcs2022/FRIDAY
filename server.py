import os
from flask import Flask, request, jsonify
from threading import Thread

from core import FridayCore

# Voice is OPTIONAL in cloud (prevents crash if ElevenLabs breaks)
try:
    from voice import speak
    VOICE_ENABLED = True
except Exception:
    VOICE_ENABLED = False

app = Flask(__name__)
ai = FridayCore()


# -----------------------------
# HEALTH CHECK ROUTE
# -----------------------------
@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "FRIDAY ONLINE",
        "message": "System is running correctly."
    })


# -----------------------------
# MAIN AI ROUTE
# -----------------------------
@app.route("/command", methods=["POST"])
def command():
    try:
        data = request.json.get("text", "")

        if not data:
            return jsonify({"response": "No input received."})

        # Try AI brain safely
        try:
            response = ai.think(data)
        except Exception as e:
            response = f"Brain error: {str(e)}"

        print("FRIDAY:", response)

        # Voice runs ONLY if available (prevents cloud crash)
        if VOICE_ENABLED:
            try:
                Thread(target=speak, args=(response,)).start()
            except Exception:
                pass

        return jsonify({"response": response})

    except Exception as e:
        return jsonify({
            "response": f"Server error: {str(e)}"
        }), 500


# -----------------------------
# CLOUD RUN ENTRY POINT
# -----------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
