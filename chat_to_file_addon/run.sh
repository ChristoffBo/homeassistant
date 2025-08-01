#!/bin/bash

# Set default output directory
OUTPUT_DIR="/share/chat_to_file"

# Create directory with full permissions
mkdir -p "$OUTPUT_DIR"
chmod 777 "$OUTPUT_DIR"

# Start the application
exec python /app/app.py