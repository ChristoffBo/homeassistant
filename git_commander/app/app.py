from flask import Flask, request, jsonify, send_file
import os
import git
import zipfile
import shutil
from datetime import datetime
import json

app = Flask(__name__)

# Load configuration from options.json
CONFIG_FILE = "/data/options.json"
REPO_DIR = "/share/git_commander_repo"
BACKUP_DIR = "/share/git_commander_backups"

def load_config():
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def setup_repo():
    config = load_config()
    repo_path = os.path.join(REPO_DIR, config["repository"])
    if not os.path.exists(repo_path):
        os.makedirs(repo_path)
        repo = git.Repo.init(repo_path)
        repo.config_writer().set_value("user", "name", config["author_name"]).release()
        repo.config_writer().set_value("user", "email", config["author_email"]).release()
        remote_url = config["github_url"] if config["git_target"] == "github" else config["gitea_url"]
        token = config["github_token"] if config["git_target"] == "github" else config["gitea_token"]
        if config["use_https"]:
            remote_url = remote_url.replace("https://", f"https://{token}:@")
        else:
            remote_url = remote_url.replace("https://", f"git@").replace("/", ":", 1) + ".git"
        repo.create_remote("origin", remote_url)
        open(os.path.join(repo_path, ".gitignore"), "a").close()
        repo.index.add([".gitignore"])
        repo.index.commit("Initial commit")
        repo.remotes.origin.push(config["branch_name"])
    return git.Repo(repo_path)

@app.route('/')
def index():
    return send_file('static/index.html')

@app.route('/api/upload', methods=['POST'])
def upload_zip():
    config = load_config()
    repo = setup_repo()
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files['file']
    if not file.filename.endswith('.zip'):
        return jsonify({"error": "Only ZIP files are allowed"}), 400
    
    upload_dir = os.path.join(REPO_DIR, config["repository"], "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    zip_path = os.path.join(upload_dir, file.filename)
    file.save(zip_path)
    
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(upload_dir)
    
    os.remove(zip_path)
    repo.index.add([upload_dir])
    repo.index.commit(config["commit_message"])
    repo.remotes.origin.push(config["branch_name"])
    
    return jsonify({"message": "File uploaded, extracted, and pushed to repository"})

@app.route('/api/git/<command>', methods=['POST'])
def git_command(command):
    repo = setup_repo()
    config = load_config()
    try:
        if command == "pull":
            repo.remotes.origin.pull(config["branch_name"])
            return jsonify({"message": "Repository pulled successfully"})
        elif command == "status":
            status = repo.git.status()
            return jsonify({"message": status})
        elif command == "reset":
            repo.git.reset('--hard')
            return jsonify({"message": "Repository reset successfully"})
        elif command == "stash":
            repo.git.stash()
            return jsonify({"message": "Changes stashed successfully"})
        elif command == "commit":
            repo.index.commit(config["commit_message"])
            repo.remotes.origin.push(config["branch_name"])
            return jsonify({"message": "Changes committed and pushed"})
        else:
            return jsonify({"error": "Invalid command"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/backup', methods=['POST'])
def backup_repo():
    config = load_config()
    os.makedirs(BACKUP_DIR, exist_ok=True)
    backup_file = os.path.join(BACKUP_DIR, f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip")
    repo_path = os.path.join(REPO_DIR, config["repository"])
    with zipfile.ZipFile(backup_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(repo_path):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, repo_path)
                zipf.write(file_path, arcname)
    return send_file(backup_file, as_attachment=True)

@app.route('/api/restore', methods=['POST'])
def restore_repo():
    config = load_config()
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files['file']
    if not file.filename.endswith('.zip'):
        return jsonify({"error": "Only ZIP files are allowed"}), 400
    
    repo_path = os.path.join(REPO_DIR, config["repository"])
    shutil.rmtree(repo_path, ignore_errors=True)
    os.makedirs(repo_path, exist_ok=True)
    zip_path = os.path.join(BACKUP_DIR, file.filename)
    file.save(zip_path)
    
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(repo_path)
    
    os.remove(zip_path)
    repo = git.Repo.init(repo_path)
    repo.index.add([repo_path])
    repo.index.commit("Restored from backup")
    repo.remotes.origin.push(config["branch_name"])
    
    return jsonify({"message": "Repository restored successfully"})

@app.route('/api/config', methods=['GET', 'POST'])
def config():
    if request.method == 'GET':
        return jsonify(load_config())
    else:
        new_config = request.json
        with open(CONFIG_FILE, 'w') as f:
            json.dump(new_config, f, indent=2)
        return jsonify({"message": "Configuration updated"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
