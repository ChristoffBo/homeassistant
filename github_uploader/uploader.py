from flask import Flask, request, send_from_directory, jsonify
import os, zipfile, tempfile, requests

app = Flask(__name__, static_folder="www", static_url_path="/")

@app.route("/")
def index():
    return send_from_directory("www", "index.html")

@app.route("/<path:path>")
def static_files(path):
    return send_from_directory("www", path)

@app.route("/upload", methods=["POST"])
def upload():
    if "zipfile" not in request.files:
        return jsonify({"status": "error", "message": "Missing zipfile"}), 400

    zip_file = request.files["zipfile"]
    repo = request.form.get("repo", "").strip()
    token = request.form.get("token", "").strip()
    folder = request.form.get("folder", "").strip()
    message = request.form.get("message", "Upload via uploader")

    if not repo or not token:
        return jsonify({"status": "error", "message": "Missing repo or token"}), 400

    with tempfile.TemporaryDirectory() as temp_dir:
        zip_path = os.path.join(temp_dir, "uploaded.zip")
        zip_file.save(zip_path)

        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(temp_dir)

        file_list = []
        for root, _, files in os.walk(temp_dir):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, temp_dir)
                if rel_path == "uploaded.zip":
                    continue
                github_path = f"{folder}/{rel_path}" if folder else rel_path
                file_list.append((full_path, github_path))

        results = []
        for local_file, github_path in file_list:
            with open(local_file, "rb") as f:
                content = f.read()

            url = f"https://api.github.com/repos/{repo}/contents/{github_path}"
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json"
            }
            get_resp = requests.get(url, headers=headers)
            sha = get_resp.json().get("sha") if get_resp.ok else None

            import base64
            payload = {
                "message": message,
                "content": base64.b64encode(content).decode("utf-8"),
            }
            if sha:
                payload["sha"] = sha

            response = requests.put(url, headers=headers, json=payload)
            if response.ok:
                results.append(f"Uploaded: {github_path}")
            else:
                results.append(f"Failed: {github_path} — {response.text}")

        return jsonify({"status": "success", "results": results})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
