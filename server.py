from flask import Flask, request, jsonify
from threading import Thread
import os
from datetime import datetime

from core import FridayCore
from voice import speak

app = Flask(__name__)
ai = FridayCore()


# =========================
# 🕶️ HUD FORMATTER
# =========================
def format_output(text, device):

    text = " ".join(text.strip().split())

    if device == "glasses":
        lines = text.split(". ")
        text = ". ".join(lines[:1])
        if len(text) > 110:
            text = text[:110] + "..."
        return f"FRIDAY\n{text}"

    return text


# =========================
# ⚡ TOOL EXECUTOR
# =========================
def run_tool(tool):

    if not tool:
        return None

    action = tool.get("action")

    if action == "get_time":
        return f"TIME\n{datetime.now().strftime('%H:%M')}"

    if action == "open_app":
        app_name = tool.get("value", "")
        os.system(f"open -a '{app_name}'")
        return f"Opened {app_name}"

    if action == "error":
        return f"ERROR\n{tool.get('value')}"

    return None


# =========================
# 🧠 ROUTER
# =========================
def route(text, device="mac", req_type="chat"):

    raw = ai.think(text)

    tool = ai.parse_tool(raw)

    result = run_tool(tool)

    if not result:
        result = raw

    result = format_output(result, device)

    if req_type != "text":
        Thread(target=speak, args=(result,)).start()

    return result


# =========================
# 🌐 API
# =========================
@app.route("/command", methods=["POST"])
def command():

    data = request.json or {}

    text = data.get("text", "")
    device = data.get("device", "mac")
    req_type = data.get("type", "chat")

    print("REQUEST:", data)

    response = route(text, device, req_type)

    print("FRIDAY:", response)

    return jsonify({"response": response})


if __name__ == "__main__":
    print("FRIDAY TOOL BRAIN ONLINE")
    app.run(host="0.0.0.0", port=8080, debug=True)
