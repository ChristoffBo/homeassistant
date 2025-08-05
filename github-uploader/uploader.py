import os
import zipfile
import tempfile
import shutil
import requests
import json
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__)

CONFIG_PATH = "/data/options.json"

def read_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}

@app.route("/")
def index():
    return send_from_directory('.', 'index.html')

@app.route("/style.css")
def style():
    return send_from_directory('.', 'style.css')

@app.route("/app.js")
def js():
    return send_from_directory('.', 'app.js')

@app.route("/upload", methods=["POST"])
def upload():
    config = read_config()
    repo = request.form.get("repo") or config.get("repo")
    token = request.form.get("token") or config.get("token")
    commit_msg = request.form.get("message", "Upload via Web UI")
    folder = request.form.get("folder")

    zip_file = request.files.get("zipfile")
    if not zip_file or not repo or not token:
        return jsonify({"status": "error", "message": "Missing zip, repo, or token"}), 400

    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, "upload.zip")
        zip_file.save(zip_path)

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            extract_dir = os.path.join(tmpdir, os.path.splitext(zip_file.filename)[0])
            zip_ref.extractall(extract_dir)

        created_files = []
        for root, dirs, files in os.walk(extract_dir):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, extract_dir)
                github_path = os.path.join(folder or os.path.splitext(zip_file.filename)[0], rel_path).replace("\\", "/")

                with open(full_path, "rb") as f:
                    content = f.read()
                encoded = content.encode("base64") if isinstance(content, str) else content.encode("base64") if hasattr(content, "encode") else content

                url = f"https://api.github.com/repos/{repo}/contents/{github_path}"
                headers = {
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github+json"
                }
                get_resp = requests.get(url, headers=headers)
                sha = get_resp.json().get("sha") if get_resp.status_code == 200 else None

                data = {
                    "message": commit_msg,
                    "content": encoded.decode("utf-8"),
                }
                if sha:
                    data["sha"] = sha

                put_resp = requests.put(url, headers=headers, data=json.dumps(data))
                if put_resp.status_code in [200, 201]:
                    created_files.append(github_path)
                else:
                    return jsonify({"status": "error", "message": f"GitHub error on {github_path}: {put_resp.text}"}), 500

    return jsonify({"status": "success", "results": created_files})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)