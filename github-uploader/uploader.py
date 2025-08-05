import os
import zipfile
import tempfile
import shutil
import requests
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__)
UPLOAD_FOLDER = "/tmp/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route("/", methods=["GET"])
def serve_index():
    return send_from_directory(".", "index.html")

@app.route("/style.css", methods=["GET"])
def serve_css():
    return send_from_directory(".", "style.css")

@app.route("/app.js", methods=["GET"])
def serve_js():
    return send_from_directory(".", "app.js")

@app.route("/upload", methods=["POST"])
def upload_zip():
    zip_file = request.files.get("zipfile")
    repo = request.form.get("repo", "").strip()
    token = request.form.get("token", "").strip()
    folder = request.form.get("folder", "").strip()
    message = request.form.get("message", "Add files via uploader")

    if not all([zip_file, repo, token]):
        return jsonify({"status": "error", "message": "Missing required fields"}), 400

    filename = secure_filename(zip_file.filename)
    folder_name = os.path.splitext(filename)[0] if not folder else folder
    extract_path = os.path.join(UPLOAD_FOLDER, folder_name)

    if os.path.exists(extract_path):
        shutil.rmtree(extract_path)
    os.makedirs(extract_path)

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        zip_file.save(tmp.name)
        with zipfile.ZipFile(tmp.name, 'r') as zip_ref:
            zip_ref.extractall(extract_path)

    results = []
    for root, dirs, files in os.walk(extract_path):
        for file in files:
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, extract_path)
            github_path = f"{folder_name}/{rel_path}".replace("\\", "/")
            with open(full_path, "rb") as f:
                content = f.read()
            res = upload_to_github(repo, token, github_path, content, message)
            results.append(f"{github_path}: {res}")

    return jsonify({"status": "success", "results": results})

def upload_to_github(repo, token, path, content, message):
    api_url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }
    get_res = requests.get(api_url, headers=headers)
    if get_res.status_code == 200:
        sha = get_res.json()["sha"]
    else:
        sha = None

    data = {
        "message": message,
        "content": content.encode("base64") if isinstance(content, str) else content.decode("latin1").encode("base64"),
        "branch": "main",
    }
    if sha:
        data["sha"] = sha

    res = requests.put(api_url, headers=headers, json=data)
    return "OK" if res.status_code in [200, 201] else f"Failed ({res.status_code})"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8085)