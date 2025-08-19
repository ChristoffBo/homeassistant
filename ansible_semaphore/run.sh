#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-10443}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@example.com}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-changeme}"
DB_PATH="/data/semaphore.db"
TMP_PATH="/tmp/semaphore"
PLAYBOOK_PATH="/data/playbooks"

mkdir -p /data "$PLAYBOOK_PATH" "$TMP_PATH"

echo "Starting Semaphore on port $PORT..."

exec /usr/local/bin/semaphore server \
    --port="$PORT" \
    --tmp-path="$TMP_PATH" \
    --playbook-path="$PLAYBOOK_PATH" \
    --bolt-path="$DB_PATH" \
    --admin="$ADMIN_USER" \
    --admin-email="$ADMIN_EMAIL" \
    --admin-password="$ADMIN_PASSWORD"
