from flask import Flask, render_template, jsonify, request
import os

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/chat', methods=['POST'])
def chat():
    return jsonify({"response": "Sample response from AI"})

@app.route('/api/export', methods=['POST'])
def export():
    return jsonify({"status": "export successful"})

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)