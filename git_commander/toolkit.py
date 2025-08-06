from flask import Flask, request, jsonify
import subprocess
import os

toolkit = Flask(__name__)

@toolkit.route('/api/git', methods=['POST'])
def git_command():
    command = request.json.get("command")
    if not command.startswith("git "):
        return jsonify({"error": "Only git commands are allowed"}), 400
    try:
        result = subprocess.check_output(command, shell=True, stderr=subprocess.STDOUT, cwd="/data")
        return jsonify({"output": result.decode()})
    except subprocess.CalledProcessError as e:
        return jsonify({"error": e.output.decode()}), 500

toolkit.run(host="0.0.0.0", port=8082)
