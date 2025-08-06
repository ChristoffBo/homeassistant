from flask import Flask, request, jsonify
import subprocess, os, json

app = Flask(__name__)
CONFIG_PATH = "/data/options.json"
REPO_DIR = "/data/gitrepo"

def run_git_command(command):
    try:
        result = subprocess.run(command, cwd=REPO_DIR, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return {"stdout": result.stdout, "stderr": result.stderr, "code": result.returncode}
    except Exception as e:
        return {"error": str(e)}

@app.route("/git/status")
def git_status():
    return jsonify(run_git_command(["git", "status"]))

@app.route("/git/pull")
def git_pull():
    return jsonify(run_git_command(["git", "pull"]))

@app.route("/git/reset")
def git_reset():
    return jsonify(run_git_command(["git", "reset", "--hard"]))

@app.route("/git/stash")
def git_stash():
    return jsonify(run_git_command(["git", "stash"]))

@app.route("/git/commit", methods=["POST"])
def git_commit():
    data = request.get_json()
    message = data.get("message", "Manual commit from Git Commander")
    subprocess.run(["git", "add", "-A"], cwd=REPO_DIR)
    return jsonify(run_git_command(["git", "commit", "-m", message]))
