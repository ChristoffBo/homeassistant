from flask import Flask, request, jsonify, render_template
from .api_clients import APIManager
from .github_handler import GitHubHandler
import os

app = Flask(__name__)
api = APIManager()
github = GitHubHandler()

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    try:
        response = api.get_response(data.get('model', os.getenv('DEFAULT_MODEL')), data['message'])
        return jsonify({"response": response})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/export", methods=["POST"])
def export():
    data = request.json
    try:
        if data['method'] == 'github':
            github.create_file(
                repo=os.getenv('GITHUB_REPO'),
                path=f"exports/{data['filename']}",
                content=data['content']
            )
            return jsonify({"status": "github_success"})
        else:
            return jsonify({
                "status": "export_ready",
                "content": data['content'],
                "filename": data['filename']
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
