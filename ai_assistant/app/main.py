from flask import Flask, jsonify
import os

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({
        "status": "running",
        "version": "3.4",
        "service": "AI Assistant"
    })

@app.route('/health')
def health():
    return jsonify({"status": "healthy"}), 200

@app.route('/api/ready')
def ready():
    return jsonify({"ready": True}), 200

if __name__ == "__main__":
    app.run(
        host='0.0.0.0',
        port=5000,
        threaded=True,
        debug=False
    )