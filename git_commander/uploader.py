from flask import Flask, request, jsonify
import zipfile, os, shutil, subprocess

uploader = Flask(__name__)

@uploader.route('/api/upload', methods=['POST'])
def upload_zip():
    file = request.files['file']
    token = request.form.get("token")
    url = request.form.get("url")
    repo_type = request.form.get("repo_type")

    if not file or not token or not url:
        return jsonify({"error": "Missing file, token, or URL"}), 400

    filename = file.filename
    foldername = os.path.splitext(filename)[0]
    upload_path = f"/data/{foldername}"
    os.makedirs(upload_path, exist_ok=True)

    zip_path = f"/data/{filename}"
    file.save(zip_path)

    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(upload_path)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    os.chdir(upload_path)
    subprocess.run("git init", shell=True)
    subprocess.run("git add .", shell=True)
    subprocess.run('git config user.name "GitCommander"', shell=True)
    subprocess.run('git config user.email "addon@example.com"', shell=True)
    subprocess.run('git commit -m "Uploaded via GitCommander"', shell=True)
    subprocess.run(f"git remote add origin {url}", shell=True)
    subprocess.run(f"git push --force https://{token}@{url.replace('https://', '')} HEAD:main", shell=True)

    return jsonify({"success": f"{filename} uploaded and pushed to {repo_type}."})

uploader.run(host="0.0.0.0", port=8081)
