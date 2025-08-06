from flask import Flask, request, jsonify, send_from_directory
import os
import json
import subprocess

app = Flask(__name__, static_folder='www', static_url_path='')

CONFIG_PATH = "/data/options.json"
REPO_DIR = "/data/gitrepo"

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/<path:path>')
def static_files(path):
    return send_from_directory(app.static_folder, path)

@app.route('/config')
def get_config():
    try:
        with open(CONFIG_PATH, 'r') as f:
            config = json.load(f)
        return jsonify(config)
    except Exception as e:
        return jsonify({"error": str(e)}), 500