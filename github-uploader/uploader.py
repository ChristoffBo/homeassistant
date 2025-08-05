import os
import json
from flask import Flask, request, send_from_directory, jsonify
from github import Github
from werkzeug.utils import secure_filename
import zipfile

app = Flask(__name__)
UPLOAD_FOLDER = "/tmp/upload"
OPTIONS_PATH = "/data/options.json"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def read_config():
    if os.path.exists(OPTIONS_PATH):
        with open(OPTIONS_PATH) as f:
            return json.load(f)
    return {}

@app.route('/')
def index():
    return send_from_directory('/', 'index.html')

@app.route('/style.css')
def css():
    return send_from_directory('/', 'style.css')

@app.route('/app.js')
def js():
    return send_from_directory('/', 'app.js')

@app.route('/upload', methods=['POST'])
def upload():
    try:
        config = read_config()

        token = request.form.get("token") or config.get("github_token", "")
        repo_name = request.form.get("repo") or config.get("github_repo", "")
        commit_msg = request.form.get("message")
        folder_override = request.form.get("folder")

        if "zipfile" not in request.files:
            return jsonify({"status": "error", "message": "No file uploaded"}), 400

        file = request.files["zipfile"]
        filename = secure_filename(file.filename)
        if not filename.lower().endswith(".zip"):
            return jsonify({"status": "error", "message": "Only ZIP files are supported"}), 400

        zip_path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(zip_path)

        target_folder = folder_override or os.path.splitext(filename)[0]

        if not token or not repo_name or not commit_msg:
            return jsonify({"status": "error", "message": "Missing token, repo or commit message"}), 400

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(UPLOAD_FOLDER)

        g = Github(token)
        repo = g.get_repo(repo_name)

        results = []

        for root, _, files in os.walk(UPLOAD_FOLDER):
            for name in files:
                if name == filename:
                    continue
                path = os.path.join(root, name)
                rel_path = os.path.relpath(path, UPLOAD_FOLDER)
                github_path = f"{target_folder}/{rel_path}".replace("\\", "/")

                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                try:
                    contents = repo.get_contents(github_path)
                    repo.update_file(github_path, commit_msg, content, contents.sha)
                    results.append(f"✅ Updated: {github_path}")
                except:
                    repo.create_file(github_path, commit_msg, content)
                    results.append(f"➕ Created: {github_path}")

        return jsonify({"status": "success", "results": results})

    except Exception as e:
        return jsonify({"status": "error", "message": f"Unhandled exception: {str(e)}"}), 500

@app.errorhandler(Exception)
def handle_error(e):
    return jsonify({
        "status": "error",
        "message": str(e)
    }), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)