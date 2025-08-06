from flask import Flask, request, jsonify, send_from_directory
import os, json, subprocess, zipfile, tempfile

app = Flask(__name__, static_folder='www', static_url_path='')

CONFIG_PATH = "/data/options.json"
REPO_DIR = "/data/gitrepo"

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(app.static_folder, path)

@app.route("/config")
def get_config():
    try:
        with open(CONFIG_PATH) as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files["file"]
    if file.filename.endswith(".zip"):
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = os.path.join(tmpdir, file.filename)
            file.save(zip_path)
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(REPO_DIR)
        return jsonify({"status": "ZIP uploaded and extracted"}), 200
    return jsonify({"error": "Invalid file type"}), 400

@app.route("/push", methods=["POST"])
def push():
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        remote = cfg.get("git_remote")
        token = cfg.get("git_token")
        author = cfg.get("git_author", "Git Commander")
        email = cfg.get("git_email", "git@example.com")
        subprocess.run(["git", "config", "user.name", author], cwd=REPO_DIR)
        subprocess.run(["git", "config", "user.email", email], cwd=REPO_DIR)
        subprocess.run(["git", "add", "."], cwd=REPO_DIR)
        subprocess.run(["git", "commit", "-m", "Upload from Git Commander"], cwd=REPO_DIR)
        subprocess.run(["git", "push", f"https://{token}@{remote}"], cwd=REPO_DIR)
        return jsonify({"status": "Pushed to remote"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
