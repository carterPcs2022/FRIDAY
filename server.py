from flask import Flask, request, jsonify
import os

app = Flask(__name__)

# SAFE IMPORT
try:
    from core import FridayCore
    CORE_OK = True
except Exception as e:
    print("CORE LOAD ERROR:", e)
    FridayCore = None
    CORE_OK = False


@app.route("/")
def home():
    return jsonify({
        "status": "FRIDAY ONLINE",
        "core_loaded": CORE_OK
    })


@app.route("/command", methods=["POST"])
def command():
    try:
        if not CORE_OK:
            return jsonify({"response": "CORE NOT AVAILABLE"})

        data = request.json.get("text", "")

        ai = FridayCore()
        result = ai.think(data)

        return jsonify({"response": result})

    except Exception as e:
        return jsonify({"response": f"SERVER ERROR: {str(e)}"})


@app.route("/health")
def health():
    return "OK", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
