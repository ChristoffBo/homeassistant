#!/usr/bin/env python3
import os
import zipfile
import tempfile
import shutil
import json
import requests
from flask import Flask, request, send_from_directory, jsonify

app = Flask(__name__, static_url_path='', static_folder='/www')
CONFIG_PATH = "/data/options.json"

def load_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

@app.route("/")
def index():
    return send_from_directory('/www', 'index.html')

@app.route("/upload", methods=["POST"])
def upload_zip():
    config = load_config()
    github_token = config.get("github_token", "").strip()
    github_repo = config.get("github_repo", "").strip()
    github_path = config.get("github_path", "").strip().strip("/")
    commit_message = config.get("commit_message", "Uploaded via GitHub Uploader").strip()

    if "zipfile" not in request.files:
        return "No file part", 400

    file = request.files["zipfile"]
    if file.filename == '':
        return "No selected file", 400

    if not github_token or not github_repo.startswith("https://github.com"):
        return "Invalid GitHub token or repository URL", 400

    tmpdir = tempfile.mkdtemp()
    zip_path = os.path.join(tmpdir, file.filename)
    file.save(zip_path)

    extract_dir = os.path.join(tmpdir, os.path.splitext(file.filename)[0])
    os.makedirs(extract_dir, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
    except zipfile.BadZipFile:
        shutil.rmtree(tmpdir)
        return "Invalid ZIP file", 400

    for root, dirs, files in os.walk(extract_dir):
        for filename in files:
            full_path = os.path.join(root, filename)
            rel_path = os.path.relpath(full_path, extract_dir)
            repo_path = f"{github_path}/{rel_path}".lstrip("/")
            upload_file_to_github(github_token, github_repo, repo_path, full_path, commit_message)

    shutil.rmtree(tmpdir)
    return "Upload complete", 200

def upload_file_to_github(token, repo_url, path, file_path, commit_msg):
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }

    owner_repo = repo_url.rstrip("/").replace("https://github.com/", "")
    api_url = f"https://api.github.com/repos/{owner_repo}/contents/{path}"

    with open(file_path, "rb") as f:
        content = f.read()
    content_b64 = content.encode("base64") if isinstance(content, str) else base64.b64encode(content).decode("utf-8")

    get_resp = requests.get(api_url, headers=headers)
    sha = get_resp.json().get("sha") if get_resp.status_code == 200 else None

    data = {
        "message": commit_msg,
        "content": content_b64,
        "branch": "main"
    }
    if sha:
        data["sha"] = sha

    resp = requests.put(api_url, headers=headers, json=data)
    if resp.status_code not in [200, 201]:
        print(f"[ERROR] Upload to {api_url} failed: {resp.status_code} - {resp.text}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)