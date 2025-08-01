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

# Set output directory
OUTPUT_DIR = "/share/chat_to_file"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# [Rest of your existing app code remains unchanged]