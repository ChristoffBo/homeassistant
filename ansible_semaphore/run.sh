#!/usr/bin/env bash
set -e

echo "[INFO] Starting Semaphore with persistent paths..."

# Ensure directories exist
mkdir -p /data/semaphore/tmp
mkdir -p /data/semaphore/playbooks
mkdir -p /data/semaphore

# Start semaphore server
exec /usr/local/bin/semaphore server \
  --config /data/semaphore/config.json