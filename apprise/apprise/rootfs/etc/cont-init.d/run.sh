#!/usr/bin/with-contenv bash
set -e

CONFIG_PATH="/data/options.json"
PORT=$(jq -r '.port // 8000' "$CONFIG_PATH")
CLI_ARGS=$(jq -r '.cli_args // ""' "$CONFIG_PATH")

echo "[INFO] Starting Apprise on port $PORT..."
exec apprise-api --port "$PORT" $CLI_ARGS
