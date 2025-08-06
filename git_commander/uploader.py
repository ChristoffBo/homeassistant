from flask import Flask, request, jsonify, send_from_directory
import os
import zipfile
import shutil
import subprocess
import json
import re

# Load config from options.json
CONFIG_PATH = "/data/options.json"
with open(CONFIG_PATH, "r") as f:
    config = json.load(f)

# GitHub and Gitea config
GITHUB_URL = config.get("github_url", "")
GITHUB_TOKEN = config.get("github_token", "")
GITEA_URL = config.get("gitea_url", "")
GITEA_TOKEN = config.get("gitea_token", "")
REPO_NAME = config.get("repository", "")
COMMIT_MESSAGE = config.get("commit_message", "Uploaded via Git Commander")

# Flask app
app = Flask(__name__, static_folder='www', static_url_path='')

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/<path:path>')
def static_files(path):
    return send_from_directory(app.static_folder, path)

@app.route('/upload', methods=['POST'])
def upload_zip():
    if 'zipfile' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['zipfile']
    if not file.filename.endswith('.zip'):
        return jsonify({'error': 'Only .zip files allowed'}), 400

    filename = file.filename
    target_folder = os.path.join("/tmp", os.path.splitext(filename)[0])
    zip_path = os.path.join("/tmp", filename)

    # Save ZIP and extract
    file.save(zip_path)
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(target_folder)

    # Upload logic (GitHub or Gitea)
    try:
        if GITHUB_URL and GITHUB_TOKEN:
            repo_url = re.sub(r'^https://', f'https://{GITHUB_TOKEN}@', GITHUB_URL)
        elif GITEA_URL and GITEA_TOKEN:
            repo_url = re.sub(r'^https://', f'https://{GITEA_TOKEN}@', GITEA_URL)
        else:
            return jsonify({'error': 'No valid Git URL or token'}), 400

        # Clone repo
        repo_path = "/tmp/repo"
        if os.path.exists(repo_path):
            shutil.rmtree(repo_path)

        subprocess.run(["git", "clone", repo_url, repo_path], check=True)

        dest_path = os.path.join(repo_path, os.path.basename(target_folder))
        if os.path.exists(dest_path):
            shutil.rmtree(dest_path)
        shutil.copytree(target_folder, dest_path)

        subprocess.run(["git", "-C", repo_path, "add", "."], check=True)
        subprocess.run(["git", "-C", repo_path, "commit", "-m", COMMIT_MESSAGE], check=True)
        subprocess.run(["git", "-C", repo_path, "push"], check=True)

        return jsonify({'success': f'Uploaded to {repo_url}'})
    except subprocess.CalledProcessError as e:
        return jsonify({'error': f'Git error: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/config', methods=['GET'])
def get_config():
    return jsonify({
        "github_url": GITHUB_URL,
        "gitea_url": GITEA_URL,
        "repository": REPO_NAME
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8099)
