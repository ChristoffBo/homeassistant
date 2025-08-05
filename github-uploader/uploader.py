import os
import zipfile
import tempfile
import requests
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__)
CONFIG_FILE = "/data/options.json"

def get_config_value(key, default=""):
    try:
        import json
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
        return config.get(key, default)
    except Exception:
        return default

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/style.css")
def style():
    return send_from_directory(".", "style.css")

@app.route("/app.js")
def js():
    return send_from_directory(".", "app.js")

@app.route("/upload", methods=["POST"])
def upload():
    try:
        token = request.form.get("token") or get_config_value("token")
        repo = request.form.get("repo") or get_config_value("repo")
        target_folder = request.form.get("folder", "").strip()
        commit_message = request.form.get("message", "Add files")

        if not token or not repo:
            return jsonify({"status": "error", "message": "Token and repo required"}), 400

        zip_file = request.files.get("zipfile")
        if not zip_file:
            return jsonify({"status": "error", "message": "No zip file uploaded"}), 400

        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = os.path.join(tmpdir, "uploaded.zip")
            zip_file.save(zip_path)

            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(tmpdir)

            root_folder = os.path.splitext(zip_file.filename)[0]
            upload_path = os.path.join(tmpdir, root_folder)

            if not os.path.exists(upload_path):
                os.makedirs(upload_path)

            results = []

            for root, _, files in os.walk(tmpdir):
                for file in files:
                    full_path = os.path.join(root, file)
                    if full_path == zip_path:
                        continue
                    rel_path = os.path.relpath(full_path, tmpdir)
                    github_path = f"{target_folder}/{rel_path}".replace("\\", "/").lstrip("/")
                    with open(full_path, "rb") as f:
                        content = f.read()
                    res = requests.put(
                        f"https://api.github.com/repos/{repo}/contents/{github_path}",
                        headers={
                            "Authorization": f"token {token}",
                            "Accept": "application/vnd.github+json",
                        },
                        json={
                            "message": commit_message,
                            "content": content.encode("base64") if isinstance(content, str) else content.decode("latin1").encode("base64"),
                        },
                    )
                    if res.status_code in (200, 201):
                        results.append(f"Uploaded {github_path}")
                    else:
                        results.append(f"Failed {github_path}: {res.text}")

        return jsonify({"status": "success", "results": results})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)