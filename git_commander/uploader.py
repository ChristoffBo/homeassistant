from flask import Flask, request, jsonify, send_from_directory, send_file
import os, zipfile, shutil, subprocess, json, tarfile, re

CONFIG_PATH = "/data/options.json"
with open(CONFIG_PATH, "r") as f:
    config = json.load(f)

GITHUB_URL = config.get("github_url", "")
GITHUB_TOKEN = config.get("github_token", "")
GITEA_URL = config.get("gitea_url", "")
GITEA_TOKEN = config.get("gitea_token", "")
REPO_NAME = config.get("repository", "")
COMMIT_MESSAGE = config.get("commit_message", "Uploaded via Git Commander")

UPLOAD_FOLDER = "/tmp/uploads"
REPO_CLONE_PATH = "/tmp/repo"
BACKUP_PATH = "/backup/git_commander_backup.tar.gz"

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
    zip_path = os.path.join("/tmp", filename)
    extract_folder = os.path.join(UPLOAD_FOLDER, os.path.splitext(filename)[0])
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    file.save(zip_path)
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_folder)
    except zipfile.BadZipFile:
        return jsonify({'error': 'Invalid ZIP file'}), 400
    try:
        if GITHUB_URL and GITHUB_TOKEN:
            repo_url = re.sub(r'^https://', f'https://{GITHUB_TOKEN}@', GITHUB_URL)
        elif GITEA_URL and GITEA_TOKEN:
            repo_url = re.sub(r'^https://', f'https://{GITEA_TOKEN}@', GITEA_URL)
        else:
            return jsonify({'error': 'No valid Git URL or token'}), 400
        if os.path.exists(REPO_CLONE_PATH):
            shutil.rmtree(REPO_CLONE_PATH)
        subprocess.run(["git", "clone", repo_url, REPO_CLONE_PATH], check=True)
        target_path = os.path.join(REPO_CLONE_PATH, os.path.basename(extract_folder))
        if os.path.exists(target_path):
            shutil.rmtree(target_path)
        shutil.copytree(extract_folder, target_path)
        subprocess.run(["git", "-C", REPO_CLONE_PATH, "add", "."], check=True)
        subprocess.run(["git", "-C", REPO_CLONE_PATH, "commit", "-m", COMMIT_MESSAGE], check=True)
        subprocess.run(["git", "-C", REPO_CLONE_PATH, "push"], check=True)
        return jsonify({'success': f'Uploaded to {repo_url}'})
    except subprocess.CalledProcessError as e:
        error_message = getattr(e, 'stderr', str(e))
        return jsonify({'error': f'Git error: {error_message}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/git', methods=['POST'])
def run_git_command():
    data = request.get_json()
    if not data or 'command' not in data:
        return jsonify({'error': 'Missing command'}), 400
    command = data['command']
    if not command.strip().startswith("git "):
        return jsonify({'error': 'Only git commands allowed'}), 400
    try:
        result = subprocess.run(command.split(), cwd=REPO_CLONE_PATH, capture_output=True, text=True)
        return jsonify({'stdout': result.stdout, 'stderr': result.stderr, 'returncode': result.returncode})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/backup', methods=['GET'])
def backup_data():
    try:
        os.makedirs(os.path.dirname(BACKUP_PATH), exist_ok=True)
        with tarfile.open(BACKUP_PATH, "w:gz") as tar:
            tar.add(REPO_CLONE_PATH, arcname=os.path.basename(REPO_CLONE_PATH))
        return send_file(BACKUP_PATH, as_attachment=True)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/restore', methods=['POST'])
def restore_data():
    if 'backupfile' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    uploaded_file = request.files['backupfile']
    temp_path = '/tmp/restore.tar.gz'
    uploaded_file.save(temp_path)
    try:
        if os.path.exists(REPO_CLONE_PATH):
            shutil.rmtree(REPO_CLONE_PATH)
        with tarfile.open(temp_path, "r:gz") as tar:
            tar.extractall(path=os.path.dirname(REPO_CLONE_PATH))
        return jsonify({'success': 'Backup restored'})
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
