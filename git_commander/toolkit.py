from flask import Flask, request, jsonify
import subprocess
import os

app = Flask(__name__)

REPO_DIR = "/data/gitrepo"

def run_git_command(args):
    try:
        result = subprocess.run(["git"] + args, cwd=REPO_DIR, capture_output=True, text=True)
        return {"stdout": result.stdout, "stderr": result.stderr, "code": result.returncode}
    except Exception as e:
        return {"error": str(e)}

@app.route("/api/git/<cmd>", methods=["POST"])
def git_command(cmd):
    commands = {
        "pull": ["pull"],
        "status": ["status"],
        "reset": ["reset", "--hard"],
        "stash": ["stash"],
        "commit": ["commit", "-am", request.json.get("message", "Update")],
        "checkout": ["checkout", request.json.get("branch", "main")]
    }
    if cmd not in commands:
        return jsonify({"error": "Invalid command"}), 400
    result = run_git_command(commands[cmd])
    return jsonify(result)