#!/usr/bin/env bash
set -e

echo "[INFO] Starting Ansible Semaphore add-on..."

# Ensure persistent folders exist
mkdir -p /data/semaphore/playbooks /data/semaphore/tmp

# Bootstrap only if database doesn’t exist
if [ ! -f /data/semaphore/semaphore.db ]; then
    echo "[INFO] Initializing Semaphore for first run..."
    semaphore setup \
      --admin "$SEMAPHORE_ADMIN" \
      --email "$SEMAPHORE_ADMIN_EMAIL" \
      --name "Home Assistant Admin" \
      --password "$SEMAPHORE_ADMIN_PASSWORD" \
      --db "$SEMAPHORE_DB"
else
    echo "[INFO] Found existing Semaphore database, reusing it..."
fi

# Start server with persistent config
exec semaphore server --config /data/semaphore/config.json