import os
import zipfile
import tempfile
import shutil
from flask import Flask, request, jsonify, send_from_directory
from github import Github

app = Flask(__name__)

@app.route("/")
def index():
    return send_from_directory("app", "index.html")

@app.route("/<path:path>")
def static_proxy(path):
    return send_from_directory("app", path)

@app.route("/upload", methods=["POST"])
def upload():
    zip_file = request.files.get("zipfile")
    repo_name = request.form.get("repo")
    token = request.form.get("token")
    folder = request.form.get("folder", "").strip().strip("/")
    commit_msg = request.form.get("message", "Add files")

    if not zip_file or not repo_name or not token:
        return jsonify({"status": "error", "message": "Missing zipfile, repo, or token"}), 400

    temp_dir = tempfile.mkdtemp()
    try:
        zip_path = os.path.join(temp_dir, "upload.zip")
        zip_file.save(zip_path)

        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(temp_dir)

        g = Github(token)
        repo = g.get_repo(repo_name)
        results = []

        for root, _, files in os.walk(temp_dir):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, temp_dir)
                if rel_path == "upload.zip":
                    continue
                with open(full_path, "rb") as f:
                    content = f.read()
                github_path = f"{folder}/{rel_path}".replace("\\", "/") if folder else rel_path.replace("\\", "/")

                try:
                    existing_file = repo.get_contents(github_path)
                    repo.update_file(github_path, commit_msg, content, existing_file.sha)
                    results.append(f"Updated: {github_path}")
                except:
                    repo.create_file(github_path, commit_msg, content)
                    results.append(f"Created: {github_path}")

        return jsonify({"status": "success", "results": results})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        shutil.rmtree(temp_dir)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)