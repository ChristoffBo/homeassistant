import os
import subprocess
import tarfile
import json
from flask import Flask, request, send_from_directory, jsonify

CONFIG_PATH = "/data/options.json"

app = Flask(__name__, static_folder='www', static_url_path='')


@app.after_request
def add_header(response):
    response.cache_control.no_store = True
    return response


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(app.static_folder, path)


@app.route("/config", methods=["GET"])
def get_config():
    if not os.path.exists(CONFIG_PATH):
        return jsonify({})

    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)

    return jsonify({
        "github_url": config.get("github_url", ""),
        "github_token": config.get("github_token", ""),
        "gitea_url": config.get("gitea_url", ""),
        "gitea_token": config.get("gitea_token", ""),
        "repository": config.get("repository", ""),
        "commit_message": config.get("commit_message", "Uploaded via Git Commander")
    })


@app.route("/upload", methods=["POST"])
def upload_zip():
    file = request.files.get("zipfile")
    if not file or not file.filename.endswith(".zip"):
        return jsonify({"error": "ZIP file required"}), 400

    zip_path = os.path.join("/tmp", file.filename)
    file.save(zip_path)

    extract_dir = os.path.join("/tmp", os.path.splitext(file.filename)[0])
    os.makedirs(extract_dir, exist_ok=True)

    subprocess.run(["unzip", "-o", zip_path, "-d", extract_dir], check=True)

    return jsonify({"success": f"{file.filename} uploaded and extracted"})


@app.route("/git", methods=["POST"])
def run_git():
    data = request.json
    command = data.get("command")
    repo = "/data/repo"

    if not command:
        return jsonify({"error": "No command given"}), 400

    try:
        result = subprocess.run(
            ["git"] + command.split(),
            cwd=repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return jsonify({
            "stdout": result.stdout,
            "stderr": result.stderr
        })
    except Exception as e:
        return jsonify({
            "error": f"Git error: {e.stderr if hasattr(e, 'stderr') else str(e)}"
        }), 500


@app.route("/backup", methods=["GET"])
def backup():
    backup_path = "/tmp/git_commander_backup.tar.gz"
    with tarfile.open(backup_path, "w:gz") as tar:
        tar.add("/data/repo", arcname="repo")
    return send_from_directory("/tmp", "git_commander_backup.tar.gz", as_attachment=True)


@app.route("/restore", methods=["POST"])
def restore():
    file = request.files.get("backupfile")
    if not file:
        return jsonify({"error": "Backup file required"}), 400

    restore_path = "/tmp/restore.tar.gz"
    file.save(restore_path)

    with tarfile.open(restore_path, "r:gz") as tar:
        tar.extractall(path="/data")

    return jsonify({"success": "Backup restored."})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8099)
