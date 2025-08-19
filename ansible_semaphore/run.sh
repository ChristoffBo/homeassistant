#!/usr/bin/env bash
set -e

DB_PATH="/data/semaphore/semaphore.db"
CONFIG_PATH="/data/semaphore/config.json"
TMP_PATH="/data/semaphore/tmp"
PLAYBOOK_PATH="/data/semaphore/playbooks"

mkdir -p /data/semaphore
mkdir -p "$TMP_PATH"
mkdir -p "$PLAYBOOK_PATH"

# If DB doesn't exist, bootstrap Semaphore
if [ ! -f "$DB_PATH" ]; then
    echo "[INFO] First run detected. Initializing Semaphore database..."
    semaphore setup \
        --admin "$SEMAPHORE_ADMIN" \
        --email "$SEMAPHORE_ADMIN_EMAIL" \
        --name "Admin" \
        --password "$SEMAPHORE_ADMIN_PASSWORD" \
        --db "$DB_PATH" \
        --tmp-path "$TMP_PATH" \
        --playbook-path "$PLAYBOOK_PATH" \
        --config "$CONFIG_PATH"
else
    echo "[INFO] Existing database found. Skipping setup."
fi

echo "[INFO] Starting Semaphore..."
exec semaphore server --config "$CONFIG_PATH"