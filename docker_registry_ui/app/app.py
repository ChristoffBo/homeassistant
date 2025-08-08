from flask import Flask, request, jsonify, send_from_directory
import os
import subprocess
import json

app = Flask(__name__)

CONFIG_PATH = "/data/options.json"
REGISTRY_HOST = "localhost"

def get_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

@app.route("/")
def index():
    return send_from_directory("/www", "index.html")

@app.route("/static/<path:path>")
def static_files(path):
    return send_from_directory("/www", path)

@app.route("/api/images", methods=["GET"])
def list_images():
    repo_path = "/data/registry/docker/registry/v2/repositories"
    images = []
    for root, dirs, files in os.walk(repo_path):
        if "_manifests" in dirs:
            image_path = os.path.relpath(root, repo_path)
            tags_path = os.path.join(root, "_manifests", "tags")
            if os.path.isdir(tags_path):
                for tag in os.listdir(tags_path):
                    images.append({
                        "image": image_path,
                        "tag": tag
                    })
    return jsonify(images)

@app.route("/api/pull", methods=["POST"])
def pull_image():
    data = request.get_json()
    image = data.get("image")
    tag = data.get("tag", "latest")
    config = get_config()
    registry_port = config.get("registry_port", 5000)
    full_image = f"{image}:{tag}"
    local_ref = f"{REGISTRY_HOST}:{registry_port}/{full_image}"
    cmd = ["skopeo", "copy", f"docker://{full_image}", f"docker://{local_ref}"]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return jsonify({"success": True})
    except subprocess.CalledProcessError as e:
        return jsonify({"success": False, "error": e.stderr.decode()}), 500

if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    app.run(host="0.0.0.0", port=port)
