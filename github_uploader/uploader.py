import os
import zipfile
import tempfile
from flask import Flask, request, send_from_directory, jsonify
from github import Github
import json

app = Flask(__name__)
CONFIG_PATH = "/data/options.json"

def get_config():
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/style.css")
def style():
    return send_from_directory(".", "style.css")

@app.route("/app.js")
def script():
    return send_from_directory(".", "app.js")

@app.route("/upload", methods=["POST"])
def upload():
    config = get_config()
    file = request.files["zipfile"]
    repo_name = request.form.get("repo", config.get("repo"))
    token = request.form.get("token", config.get("token"))
    folder = request.form.get("folder", config.get("folder"))
    message = request.form.get("message", config.get("message"))

    if not all([file, repo_name, token, message]):
        return jsonify({"status": "error", "message": "Missing required fields"}), 400

    with tempfile.TemporaryDirectory() as tmpdirname:
        zip_path = os.path.join(tmpdirname, file.filename)
        file.save(zip_path)

        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(tmpdirname)

        g = Github(token)
        repo = g.get_repo(repo_name)

        results = []

        for root, _, files in os.walk(tmpdirname):
            for name in files:
                full_path = os.path.join(root, name)
                rel_path = os.path.relpath(full_path, tmpdirname)
                github_path = f"{folder}/{rel_path}".replace("\", "/") if folder else rel_path.replace("\", "/")

                with open(full_path, "rb") as f:
                    content = f.read()

                try:
                    existing = repo.get_contents(github_path)
                    repo.update_file(existing.path, message, content, existing.sha)
                    results.append(f"Updated: {github_path}")
                except:
                    repo.create_file(github_path, message, content)
                    results.append(f"Created: {github_path}")

        return jsonify({"status": "success", "results": results})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)