#!/usr/bin/env bash
set -e

DATA_DIR="/share/ansible_semaphore"

echo "[INFO] Ensuring persistent directories in $DATA_DIR ..."
mkdir -p "$DATA_DIR/playbooks" "$DATA_DIR/tmp"

# Ensure DB file exists
if [ ! -f "$DATA_DIR/database.boltdb" ]; then
  echo "[INFO] First run detected. Initializing Semaphore database..."
  semaphore setup \
    --db="bolt" \
    --bolt-path="$DATA_DIR/database.boltdb" \
    --admin="$SEMAPHORE_ADMIN" \
    --email="$SEMAPHORE_ADMIN_EMAIL" \
    --password="$SEMAPHORE_ADMIN_PASSWORD" \
    --tmp-path="$DATA_DIR/tmp" \
    --playbook-path="$DATA_DIR/playbooks"
fi

echo "[INFO] Starting Semaphore..."
exec semaphore server \
  --config="$DATA_DIR/config.json" \
  --port=3000