import os
from flask import Flask, request, jsonify
from threading import Thread

# -----------------------------
# SAFE IMPORT (prevents boot crash)
# -----------------------------
try:
    from core import FridayCore
except Exception as e:
    FridayCore = None
    print("CORE IMPORT FAILED:", e)

# -----------------------------
# OPTIONAL VOICE (never crashes server)
# -----------------------------
try:
    from voice import speak
    VOICE_ENABLED = True
except Exception:
    VOICE_ENABLED = False


app = Flask(__name__)

# AI is lazy-loaded (IMPORTANT for Cloud Run stability)
ai = None


# -----------------------------
# HEALTH CHECK
# -----------------------------
@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "FRIDAY ONLINE",
        "core_loaded": FridayCore is not None
    })


# -----------------------------
# MAIN COMMAND ROUTE
# -----------------------------
@app.route("/command", methods=["POST"])
def command():
    global ai

    try:
        data = request.json.get("text", "")

        if not data:
            return jsonify({"response": "No input received."})

        # Lazy init (prevents boot failure)
        if ai is None and FridayCore is not None:
            ai = FridayCore()

        if ai is None:
            return jsonify({"response": "FRIDAY CORE NOT AVAILABLE"})

        response = ai.think(data)

        print("FRIDAY:", response)

        # Optional voice (non-blocking)
        if VOICE_ENABLED:
            try:
                Thread(target=speak, args=(response,)).start()
            except Exception:
                pass

        return jsonify({"response": response})

    except Exception as e:
        return jsonify({"response": f"Server error: {str(e)}"})


# -----------------------------
# CLOUD RUN ENTRY POINT
# -----------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
