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

# Manual config fallback
try:
    OUTPUT_DIR = "/share/chat_to_file"
    if os.path.exists("/data/options.json"):
        with open("/data/options.json") as f:
            config = json.load(f)
            OUTPUT_DIR = config.get("output_dir", OUTPUT_DIR)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
except Exception as e:
    logging.error(f"Config error: {e}")
    OUTPUT_DIR = "/share/chat_to_file"  # Hardcoded fallback
    os.makedirs(OUTPUT_DIR, exist_ok=True)

# ... [rest of your existing app.py code] ...