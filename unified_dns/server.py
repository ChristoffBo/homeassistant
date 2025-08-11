import os
import json
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

CONFIG_PATH = "/data/options.json"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WWW_DIR = os.path.join(BASE_DIR, "www")

app = Flask(__name__, static_folder=WWW_DIR, static_url_path="")
CORS(app)

# ======== Helpers ========
def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    return {}

def save_config(data):
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)

# ======== API Endpoints ========

@app.route("/api/options", methods=["GET"])
def get_options():
    return jsonify(load_config())

@app.route("/api/options", methods=["POST"])
def set_options():
    try:
        data = request.get_json(force=True)
        cfg = load_config()
        cfg.update(data)
        save_config(cfg)
        return jsonify({"status": "ok", "message": "Options saved"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route("/api/stats", methods=["GET"])
def get_stats():
    # Placeholder: Implement actual stats collection later
    return jsonify({"status": "ok", "stats": {}})

# ======== Static Files ========

@app.route("/")
def index():
    return send_from_directory(WWW_DIR, "index.html")

@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(WWW_DIR, path)

# ======== Main ========
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8067))
    app.run(host="0.0.0.0", port=port, debug=True)