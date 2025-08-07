import os
import json
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from github import Github

CONFIG_PATH = "/data/options.json"
UPLOAD_DIR = "/tmp/uploads"

app = Flask(__name__)
os.makedirs(UPLOAD_DIR, exist_ok=True)

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

@app.route("/")
def index():
    return send_from_directory("www", "index.html")

@app.route("/<path:path>")
def static_files(path):
    return send_from_directory("www", path)

@app.route("/upload", methods=["POST"])
def upload_file():
    config = load_config()
    token = config.get("github_token")
    repo_url = config.get("repository_url")
    target_path = config.get("target_path")
    commit_msg = config.get("commit_message", "Upload via GitHub Uploader")

    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    filename = secure_filename(file.filename)
    local_path = os.path.join(UPLOAD_DIR, filename)
    file.save(local_path)

    try:
        g = Github(token)
        parts = repo_url.rstrip("/").split("/")
        repo_name = f"{parts[-2]}/{parts[-1]}"
        repo = g.get_repo(repo_name)

        with open(local_path, "rb") as f:
            content = f.read()

        github_path = f"{target_path.rstrip('/')}/{filename}"
        try:
            existing = repo.get_contents(github_path)
            repo.update_file(github_path, commit_msg, content, existing.sha)
        except:
            repo.create_file(github_path, commit_msg, content)

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7860)
