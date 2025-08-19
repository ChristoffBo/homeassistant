#!/usr/bin/env bash
set -e

echo "[INFO] Starting Semaphore with persistent paths..."

# Ensure directories exist in writable HA paths
mkdir -p /config/semaphore/tmp
mkdir -p /config/semaphore
mkdir -p /share/semaphore/playbooks

# Launch semaphore server
exec /usr/local/bin/semaphore server \
  --config /config/semaphore/config.json