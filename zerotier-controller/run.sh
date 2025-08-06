#!/bin/bash
set -e

CONFIG_PATH="/data/options.json"
ZT_DATA_DIR="/var/lib/zerotier-one"

# Read options
CONTROLLER_PORT=$(jq -r '.controller_port // 9993' "$CONFIG_PATH")
WEBUI_PORT=$(jq -r '.webui_port // 8080' "$CONFIG_PATH")

echo "[INFO] Starting ZeroTier Controller on port $CONTROLLER_PORT"
mkdir -p "$ZT_DATA_DIR"
zerotier-one -p"$CONTROLLER_PORT" -U -d

# Wait for identity file to be generated
while [ ! -f "$ZT_DATA_DIR/identity.public" ]; do
  echo "[INFO] Waiting for ZeroTier identity to generate..."
  sleep 2
done

echo "[INFO] Identity ready:"
cat "$ZT_DATA_DIR/identity.public"

echo "[INFO] Launching API backend on port $WEBUI_PORT"
/usr/bin/python3 /app/backend.py "$WEBUI_PORT" &
echo "[INFO] Backend started"

# Serve frontend
echo "[INFO] Starting Web UI from /www"
cd /www
python3 -m http.server "$WEBUI_PORT"