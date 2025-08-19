#!/usr/bin/env bash
set -e

echo "[INFO] Starting Semaphore with persistent paths..."

# Make sure persistent directories exist
mkdir -p /data/semaphore
mkdir -p /share/semaphore/tmp
mkdir -p /share/semaphore/playbooks

# Fix permissions to allow semaphore to write
chown -R root:root /data/semaphore /share/semaphore || true

# Launch semaphore using persistent config
exec /usr/bin/semaphore server \
  --config /data/semaphore/config.json