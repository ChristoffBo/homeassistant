#!/bin/sh

# Load HA config
OUTPUT_DIR=$(jq -r '.output_dir // "/share/chat_to_file"' /data/options.json)
mkdir -p "$OUTPUT_DIR"

# Start the app
python /app/app.py
