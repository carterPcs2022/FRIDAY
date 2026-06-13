import os
from flask import Flask, request, jsonify

app = Flask(__name__)

# -----------------------------
# CORE IMPORT TEST (SAFE)
# -----------------------------
try:
    from core import FridayCore
    CORE_OK = True
    print("CORE IMPORT SUCCESS")
except Exception as e:
    FridayCore = None
    CORE_OK = False
    print("CORE IMPORT FAILED:", e)


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "FRIDAY ONLINE",
        "core_loaded": CORE_OK
    })


@app.route("/debug-core")
def debug_core():
    try:
        import core
        return jsonify({
            "core_file": str(core),
            "attributes": dir(core)
        })
    except Exception as e:
        return str(e)


@app.route("/command", methods=["POST"])
def command():
    data = request.json.get("text", "")

    if not data:
        return jsonify({"response": "No input received."})

    if not CORE_OK:
        return jsonify({"response": "CORE NOT LOADED"})

    ai = FridayCore()
    return jsonify({"response": ai.think(data)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
