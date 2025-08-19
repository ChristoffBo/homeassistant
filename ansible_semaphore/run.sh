#!/usr/bin/env bash
set -e

echo "[INFO] Starting Semaphore with persistent paths..."

mkdir -p /data/semaphore/tmp
mkdir -p /data/semaphore/playbooks
mkdir -p /data/semaphore

exec /usr/local/bin/semaphore server \
  --config /data/semaphore/config.json