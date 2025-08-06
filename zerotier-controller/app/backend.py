from flask import Flask, jsonify, request
from flask_cors import CORS
import subprocess
import os
import sys

app = Flask(__name__)
CORS(app)

ZT_CLI = "/usr/sbin/zerotier-cli"
ZT_DATA_DIR = "/var/lib/zerotier-one"

def run_command(cmd):
    try:
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode()
        return {"success": True, "output": output.strip()}
    except subprocess.CalledProcessError as e:
        return {"success": False, "output": e.output.decode().strip()}

@app.route("/api/identity", methods=["GET"])
def get_identity():
    try:
        with open(os.path.join(ZT_DATA_DIR, "identity.public"), "r") as f:
            return jsonify({"success": True, "identity": f.read().strip()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/api/networks", methods=["GET"])
def list_networks():
    return run_command([ZT_CLI, "listnetworks"])

@app.route("/api/status", methods=["GET"])
def status():
    return run_command([ZT_CLI, "status"])

@app.route("/api/info", methods=["GET"])
def info():
    return run_command([ZT_CLI, "info"])

@app.route("/api/join", methods=["POST"])
def join_network():
    data = request.get_json()
    network_id = data.get("network_id")
    if not network_id:
        return jsonify({"success": False, "error": "Missing network_id"})
    return run_command([ZT_CLI, "join", network_id])

@app.route("/api/leave", methods=["POST"])
def leave_network():
    data = request.get_json()
    network_id = data.get("network_id")
    if not network_id:
        return jsonify({"success": False, "error": "Missing network_id"})
    return run_command([ZT_CLI, "leave", network_id])

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    app.run(host="0.0.0.0", port=port)