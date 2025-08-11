#!/usr/bin/env python3
import os
import json
from flask import Flask, request, jsonify, send_from_directory

CONFIG_PATH = "/data/options.json"
WWW_PATH = "/www"

app = Flask(__name__, static_folder=WWW_PATH, static_url_path='')

# -------------------------
# Helpers
# -------------------------
def read_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    return {}

def save_config(data):
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)

# -------------------------
# API Routes
# -------------------------
@app.route("/api/options", methods=["GET", "POST"])
def api_options():
    if request.method == "GET":
        return jsonify(read_config())
    elif request.method == "POST":
        try:
            payload = request.get_json(force=True)
            save_config(payload)
            return jsonify({"status": "ok"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 400

@app.route("/api/stats", methods=["GET"])
def api_stats():
    # Placeholder for stats fetch from servers in config
    return jsonify({"status": "ok", "stats": {}})

# -------------------------
# Static UI
# -------------------------
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_ui(path):
    if path != "" and os.path.exists(os.path.join(WWW_PATH, path)):
        return send_from_directory(WWW_PATH, path)
    else:
        return send_from_directory(WWW_PATH, "index.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8067)), debug=True)