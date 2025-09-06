#!/usr/bin/with-contenv bash
set -e

# Best effort update
apt-get update || true
apt-get upgrade -y || true

# Get port from options.json
PORT=$(jq -r '.ui_port' /data/options.json)

echo "[INFO] Starting Rundeck on port ${PORT}..."

# Rundeck uses /home/rundeck/server/config by default
# We map HA's /config to persist it
exec java -jar /home/rundeck/rundeck.war --server.port=${PORT}
