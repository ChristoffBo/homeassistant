#!/usr/bin/with-contenv bash
set -e

CONFIG="/data/options.json"

PORT=$(grep -oP '"listen_port"\s*:\s*\K[0-9]+' "$CONFIG" || echo "80")
BASE_URL=$(grep -oP '"base_url"\s*:\s*"\K[^"]+' "$CONFIG" || echo "")
CACHE_FILE=$(grep -oP '"cache_file"\s*:\s*"\K[^"]+' "$CONFIG" || echo "/data/cache.db")
AUTH_FILE=$(grep -oP '"auth_file"\s*:\s*"\K[^"]+' "$CONFIG" || echo "/data/user.db")
ATTACH_DIR=$(grep -oP '"attachment_cache_dir"\s*:\s*"\K[^"]+' "$CONFIG" || echo "/data/attachments")
ENABLE_AUTH=$(grep -oP '"enable_auth"\s*:\s*\K(true|false)' "$CONFIG" || echo "false")
ENABLE_ATTACH=$(grep -oP '"enable_file_attachments"\s*:\s*\K(true|false)' "$CONFIG" || echo "true")

echo "[INFO] Starting ntfy on port $PORT"

exec ntfy serve \
  --listen ":$PORT" \
  --cache-file "$CACHE_FILE" \
  --attachment-cache-dir "$ATTACH_DIR" \
  $( [ "$BASE_URL" != "" ] && echo "--base-url $BASE_URL" ) \
  $( [ "$ENABLE_AUTH" = "true" ] && echo "--auth-file $AUTH_FILE" ) \
  $( [ "$ENABLE_ATTACH" = "false" ] && echo "--no-file-attachments" )
