#!/bin/bash
set -e

CONFIG_PATH="/data/options.json"
REGISTRY_DATA="/data/registry"
UI_PORT=$(jq -r '.webui_port' "$CONFIG_PATH")
REGISTRY_PORT=$(jq -r '.registry_port' "$CONFIG_PATH")
INITIAL_IMAGES=$(jq -r '.initial_pull_images[]?' "$CONFIG_PATH")

# Create registry data dir
mkdir -p "$REGISTRY_DATA"

# Start registry in background
echo "[INFO] Starting Docker Registry on port $REGISTRY_PORT"
registry serve /etc/docker/registry/config.yml &

# Wait a few seconds for registry to become responsive
sleep 3

# Pull initial images if any
for IMAGE in $INITIAL_IMAGES; do
    echo "[INFO] Pulling initial image: $IMAGE"
    skopeo copy docker://$IMAGE docker://localhost:$REGISTRY_PORT/$IMAGE || echo "[WARN] Failed to pull $IMAGE"
done

# Start the Flask UI backend
echo "[INFO] Starting Web UI on port $UI_PORT"
cd /app && python3 app.py "$UI_PORT"
