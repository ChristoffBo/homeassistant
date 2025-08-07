from flask import Flask, request, jsonify
import zipfile, os, subprocess

app = Flask(__name__)

@app.route('/api/upload', methods=['POST'])
def upload_zip():
    file = request.files['file']
    url = request.form.get("url")
    token = request.form.get("token")

    if not file or not url or not token:
        return jsonify({"error": "Missing data"}), 400

    filename = file.filename
    folder = os.path.splitext(filename)[0]
    path = f"/data/{folder}"
    os.makedirs(path, exist_ok=True)
    zip_path = f"/data/{filename}"
    file.save(zip_path)

    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(path)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    os.chdir(path)
    subprocess.run("git init", shell=True)
    subprocess.run("git add .", shell=True)
    subprocess.run('git config user.name "Uploader"', shell=True)
    subprocess.run('git config user.email "uploader@example.com"', shell=True)
    subprocess.run('git commit -m "Upload via GitHub Uploader"', shell=True)
    subprocess.run(f"git remote add origin {url}", shell=True)
    subprocess.run(f"git push --force https://{token}@{url.replace('https://', '')} HEAD:main", shell=True)

    return jsonify({"success": f"Uploaded and pushed to {url}."})

app.run(host="0.0.0.0", port=8080)
