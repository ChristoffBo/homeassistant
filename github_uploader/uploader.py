#!/usr/bin/env python3
import os
import json
import zipfile
import tempfile
import shutil
import requests
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
import re
import base64

CONFIG_PATH = "/data/options.json"
UPLOAD_DIR = "/data/uploads"

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_DIR
os.makedirs(UPLOAD_DIR, exist_ok=True)

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

def extract_owner_repo(github_url):
    match = re.match(r"https?://github\\.com/([^/]+)/([^/]+)", github_url)
    if not match:
        raise ValueError("Invalid GitHub repo URL format. Must be like: https://github.com/owner/repo")
    return match.group(1), match.group(2)

def upload_file_to_github(token, owner, repo, path_in_repo, file_path, commit_message):
    with open(file_path, "rb") as f:
        content = f.read()
    encoded_content = base64.b64encode(content).decode("utf-8")

    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path_in_repo}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json"
    }

    # Check if file already exists (to include sha for updates)
    get_response = requests.get(api_url, headers=headers)
    if get_response.status_code == 200:
        sha = get_response.json().get("sha", "")
    else:
        sha = None

    data = {
        "message": commit_message,
        "content": encoded_content,
        "branch": "main"
    }

    if sha:
        data["sha"] = sha

    response = requests.put(api_url, headers=headers, json=data)
    if response.status_code not in [200, 201]:
        print(f"[ERROR] GitHub upload failed for {path_in_repo}: {response.status_code} - {response.text}")
        return False
    return True

@app.route("/", methods=["GET"])
def index():
    return "GitHub Uploader backend is running.", 200

@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    config = load_config()
    token = config.get("github_token", "").strip()
    repo_url = config.get("github_repo", "").strip()
    commit_message = config.get("commit_message", "Uploaded via GitHub Uploader").strip()

    try:
        owner, repo = extract_owner_repo(repo_url)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    zip_filename = secure_filename(file.filename)
    base_folder_name = os.path.splitext(zip_filename)[0]

    upload_path = os.path.join(app.config["UPLOAD_FOLDER"], zip_filename)
    file.save(upload_path)

    extract_dir = tempfile.mkdtemp()
    with zipfile.ZipFile(upload_path, "r") as zip_ref:
        zip_ref.extractall(extract_dir)

    success_count = 0
    failure_count = 0

    for root, _, files in os.walk(extract_dir):
        for f in files:
            abs_path = os.path.join(root, f)
            rel_path = os.path.relpath(abs_path, extract_dir)
            github_path = f"{base_folder_name}/{rel_path}".replace("\\", "/")

            print(f"[INFO] Uploading {rel_path} to GitHub path: {github_path}")
            ok = upload_file_to_github(token, owner, repo, github_path, abs_path, commit_message)
            if ok:
                success_count += 1
            else:
                failure_count += 1

    shutil.rmtree(extract_dir)
    os.remove(upload_path)

    return jsonify({
        "status": "complete",
        "uploaded": success_count,
        "failed": failure_count
    }), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
