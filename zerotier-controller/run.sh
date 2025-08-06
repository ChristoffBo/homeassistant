#!/usr/bin/with-contenv bash
set -e

CONFIG_PATH="/data/options.json"
ZT_DATA_DIR="/var/lib/zerotier-one"

CONTROLLER_PORT=$(jq -r '.controller_port // 9993' "$CONFIG_PATH")
WEBUI_PORT=$(jq -r '.webui_port // 8080' "$CONFIG_PATH")

echo "[INFO] Starting ZeroTier Controller on port $CONTROLLER_PORT"
mkdir -p "$ZT_DATA_DIR"
zerotier-one -p"$CONTROLLER_PORT" -U &

# Wait for ZeroTier to initialize
while [ ! -f "$ZT_DATA_DIR/identity.public" ]; do
  echo "[INFO] Waiting for ZeroTier identity..."
  sleep 2
done

echo "[INFO] Identity:"
cat "$ZT_DATA_DIR/identity.public"

echo "[INFO] Launching backend API"
/usr/bin/python3 /app/backend.py "$WEBUI_PORT" &

echo "[INFO] Starting Web UI"
/usr/bin/python3 -m http.server "$WEBUI_PORT" --directory /www