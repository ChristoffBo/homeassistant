#!/usr/bin/with-contenv bash
set -e

CONFIG_PATH="/data/options.json"
ZT_DATA_DIR="/var/lib/zerotier-one"

CONTROLLER_PORT=$(jq -r '.controller_port // 9993' "$CONFIG_PATH")
WEBUI_PORT=$(jq -r '.webui_port // 8080' "$CONFIG_PATH")

echo "[INFO] Starting ZeroTier Controller on port $CONTROLLER_PORT"
mkdir -p "$ZT_DATA_DIR"

# Run in controller mode
zerotier-one -p"$CONTROLLER_PORT" -U &

# Wait for identity
while [ ! -f "$ZT_DATA_DIR/identity.public" ]; do
  echo "[INFO] Waiting for ZeroTier identity..."
  sleep 2
done

echo "[INFO] Identity:"
cat "$ZT_DATA_DIR/identity.public"

echo "[INFO] Launching backend API"
python3 /app/backend.py "$WEBUI_PORT" &

echo "[INFO] Starting frontend (Web UI)"
exec python3 -m http.server "$WEBUI_PORT" --directory /www