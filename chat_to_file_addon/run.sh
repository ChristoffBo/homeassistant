#!/bin/sh

# Fallback if jq fails
OUTPUT_DIR="/share/chat_to_file"
if [ -f "/data/options.json" ]; then
    OUTPUT_DIR=$(grep -o '"output_dir": *"[^"]*"' /data/options.json | cut -d'"' -f4 || echo "$OUTPUT_DIR")
fi

mkdir -p "$OUTPUT_DIR"
chmod 777 "$OUTPUT_DIR"  # Ensure write permissions

# Start the app
python /app/app.py