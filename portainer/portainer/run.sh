#!/usr/bin/env bash
set -e

CONFIG_PATH="/data/options.json"

PORT=$(jq -r '.port // 9000' "$CONFIG_PATH")
CLI_ARGS=$(jq -r '.cli_args // ""' "$CONFIG_PATH")
IMAGE=$(jq -r '.image_override // "portainer/portainer-ce"' "$CONFIG_PATH")

echo "[INFO] Starting Portainer on port $PORT with image $IMAGE"

docker run -d \
  -p ${PORT}:9000 \
  -v /data/portainer:/data \
  --name portainer-addon \
  --restart always \
  $IMAGE $CLI_ARGS

wait
