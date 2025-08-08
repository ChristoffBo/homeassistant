#!/usr/bin/with-contenv bash
set -e

CONFIG_PATH="/data/options.json"

export ZTNCUI_USERNAME=$(jq -r '.admin_user' "$CONFIG_PATH")
export ZTNCUI_PASSWORD=$(jq -r '.admin_password' "$CONFIG_PATH")
export ZTNCUI_HOME_DIR=$(jq -r '.zt_home' "$CONFIG_PATH")
export ZTNCUI_HOST=$(jq -r '.hostname' "$CONFIG_PATH")
export ZTNCUI_EMAIL=$(jq -r '.email' "$CONFIG_PATH")
export ZTNCUI_CONTROLLER_NETWORK_ID=$(jq -r '.controller_network_id' "$CONFIG_PATH")

echo "[INFO] Starting ZTNCUI with user: $ZTNCUI_USERNAME"
exec /app/ztncui.py