from flask import Flask, jsonify, render_template, request
import time
import os

app = Flask(__name__)

# Health endpoints
@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "time": time.time(),
        "version": "3.6"
    }), 200

@app.route('/ingress_ready')
def ingress_ready():
    return jsonify({"ready": True}), 200

# Web UI
@app.route('/')
def home():
    return render_template('index.html')

# API endpoints
@app.route('/api/chat', methods=['POST'])
def chat():
    return jsonify({"response": "AI response placeholder"})

@app.route('/api/export', methods=['POST'])
def export():
    return jsonify({"status": "export successful"})

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, threaded=True)