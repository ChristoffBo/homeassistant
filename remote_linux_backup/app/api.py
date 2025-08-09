import os
import json
import time
import subprocess
import threading
import hashlib
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename

CONFIG_PATH = None
app = Flask(__name__)

# Load configuration
def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)

# Gotify notification
def send_gotify(title, message):
    cfg = load_config()
    if not cfg.get("gotify_enabled"):
        return
    url = cfg.get("gotify_url")
    token = cfg.get("gotify_token")
    if not url or not token:
        return
    try:
        subprocess.run(
            [
                "curl", "-s", "-X", "POST", f"{url}/message",
                "-F", f"token={token}",
                "-F", f"title={title}",
                "-F", f"message={message}"
            ],
            check=False
        )
    except Exception as e:
        print(f"[Gotify Error] {e}")

# Backup execution
def run_backup(job):
    start_time = time.time()
    destination = job.get("destination")
    backup_name = job.get("name") or f"backup_{int(start_time)}"
    filename = os.path.join(destination, f"{backup_name}.img.gz")

    # Build SSH/rsync/dd command
    ssh_host = job.get("ssh_host")
    ssh_user = job.get("ssh_user")
    ssh_pass = job.get("ssh_pass")
    ssh_port = job.get("ssh_port", 22)
    bandwidth = job.get("bandwidth_limit", 0)
    excludes = job.get("excludes", "")
    verify = job.get("verify", False)

    if job.get("mode") == "dd":
        cmd = f"ssh -p {ssh_port} {ssh_user}@{ssh_host} 'sudo dd if={job['source']}' | gzip -c > '{filename}'"
    elif job.get("mode") == "rsync":
        exclude_args = " ".join([f"--exclude='{e.strip()}'" for e in excludes.split(",") if e.strip()])
        bwlimit = f"--bwlimit={bandwidth}" if bandwidth > 0 else ""
        cmd = f"rsync -avz -e 'ssh -p {ssh_port}' {exclude_args} {bwlimit} {ssh_user}@{ssh_host}:{job['source']} {destination}"
    else:
        return False, "Unsupported mode"

    os.makedirs(destination, exist_ok=True)
    print(f"[Backup] Running: {cmd}")
    result = subprocess.run(cmd, shell=True)

    elapsed = round(time.time() - start_time, 2)
    backup_size = 0
    if os.path.exists(filename):
        backup_size = os.path.getsize(filename)

    if result.returncode == 0:
        msg = f"Backup completed: {backup_name}\nTime: {elapsed}s\nSize: {backup_size} bytes\nDestination: {destination}"
        send_gotify("Backup Success", msg)
        return True, msg
    else:
        msg = f"Backup failed: {backup_name}"
        send_gotify("Backup Failed", msg)
        return False, msg

@app.route("/api/config", methods=["GET", "POST"])
def config_api():
    if request.method == "GET":
        return jsonify(load_config())
    data = request.json
    save_config(data)
    return jsonify({"status": "ok"})

@app.route("/api/run_job", methods=["POST"])
def run_job():
    job = request.json
    threading.Thread(target=run_backup, args=(job,)).start()
    return jsonify({"status": "started"})

@app.route("/", defaults={"path": "index.html"})
@app.route("/<path:path>")
def static_files(path):
    return send_from_directory("/app/www", path)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8066)
    parser.add_argument("--config", type=str, required=True)
    args = parser.parse_args()
    CONFIG_PATH = args.config
    app.run(host="0.0.0.0", port=args.port)
