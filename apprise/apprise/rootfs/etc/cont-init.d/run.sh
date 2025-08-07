#!/usr/bin/with-contenv bash
set -e

CONFIG_PATH="/data/options.json"
PORT=$(jq -r '.port // 8000' "$CONFIG_PATH")
CLI_ARGS=$(jq -r '.cli_args // ""' "$CONFIG_PATH")

echo "[INFO] Starting official Apprise web UI on port $PORT..."
exec apprise-api --bind 0.0.0.0 --port "$PORT" $CLI_ARGS
