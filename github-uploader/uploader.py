import os
from flask import Flask, request, send_from_directory, jsonify
from github import Github
from werkzeug.utils import secure_filename
import zipfile

app = Flask(__name__)
UPLOAD_FOLDER = "/tmp/upload"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

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
    token = request.form.get("token")
    repo_name = request.form.get("repo")
    target_folder = request.form.get("folder")
    commit_msg = request.form.get("message")

    file = request.files["zipfile"]
    filename = secure_filename(file.filename)
    zip_path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(zip_path)

    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(UPLOAD_FOLDER)

    g = Github(token)
    repo = g.get_repo(repo_name)

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
            except:
                repo.create_file(github_path, commit_msg, content)

    return jsonify({"status": "success"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)