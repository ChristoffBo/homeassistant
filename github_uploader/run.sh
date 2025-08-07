#!/usr/bin/with-contenv bash
set -e

CONFIG_PATH="/data/options.json"
WEBUI_PORT=$(jq -r '.webui_port // 8080' "$CONFIG_PATH")

echo "[INFO] Starting GitHub Uploader add-on on port $WEBUI_PORT..."

# Wait for config and token if needed
if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "[ERROR] Missing config file: $CONFIG_PATH"
  exit 1
fi

# Show configured options
echo "[INFO] Configuration:"
jq '.' "$CONFIG_PATH" || echo "[WARN] Could not parse config."

# Ensure web files are in place
if [[ ! -f /www/index.html ]]; then
  echo "[ERROR] /www/index.html not found. Cannot start UI."
  exit 1
fi

# Start the frontend Web UI
echo "[INFO] Starting web UI server from /www"
exec python3 -m http.server "$WEBUI_PORT" --directory /www