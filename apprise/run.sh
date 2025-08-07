#!/bin/bash
set -e

CONFIG_PATH="/data/options.json"
PORT=$(grep -oP '"port"\s*:\s*\K[0-9]+' "$CONFIG_PATH" || echo "8000")

echo "[INFO] Launching Apprise API on port $PORT"
exec /app/apprise-api --bind 0.0.0.0 --port "$PORT"
