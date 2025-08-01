import os
import json
import logging
from datetime import datetime
from flask import Flask, request, render_template, send_file

app = Flask(__name__)

# Configure logging
logging.basicConfig(
    filename='/app/logs/chat_to_file.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Hardcoded configuration - no jq dependency
OUTPUT_DIR = "/share/chat_to_file"
os.makedirs(OUTPUT_DIR, exist_ok=True)

@app.route("/")
def home():
    return "Chat to File is running!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)