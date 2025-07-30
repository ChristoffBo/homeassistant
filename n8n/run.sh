#!/usr/bin/env bash
set -e

CONFIG_PATH=/data/options.json

PORT=$(jq -r '.port' "$CONFIG_PATH")
TIMEZONE=$(jq -r '.timezone' "$CONFIG_PATH")
BASIC_AUTH_ACTIVE=$(jq -r '.basic_auth_active' "$CONFIG_PATH")
BASIC_AUTH_USER=$(jq -r '.basic_auth_user' "$CONFIG_PATH")
BASIC_AUTH_PASS=$(jq -r '.basic_auth_password' "$CONFIG_PATH")

ENV_VARS=(
  -e N8N_PORT=$PORT
  -e N8N_HOST=0.0.0.0
  -e TZ=$TIMEZONE
)

if [ "$BASIC_AUTH_ACTIVE" = true ]; then
  ENV_VARS+=(
    -e N8N_BASIC_AUTH_ACTIVE=true
    -e N8N_BASIC_AUTH_USER="$BASIC_AUTH_USER"
    -e N8N_BASIC_AUTH_PASSWORD="$BASIC_AUTH_PASS"
  )
else
  ENV_VARS+=(-e N8N_BASIC_AUTH_ACTIVE=false)
fi

docker run --rm \
  -p $PORT:$PORT \
  -v /data:/home/node/.n8n \
  "${ENV_VARS[@]}" \
  n8nio/n8n:1.48.0