#!/usr/bin/env bash
set -e

DATA_DIR="/share/ansible_semaphore"
CONFIG_FILE="$DATA_DIR/config.json"

echo "[INFO] Ensuring persistent directories in $DATA_DIR ..."
mkdir -p "$DATA_DIR/tmp" "$DATA_DIR/playbooks"

# Generate config.json on first run
if [ ! -f "$CONFIG_FILE" ]; then
  echo "[INFO] First run detected. Generating config.json..."
  /usr/local/bin/semaphore setup \
    --config="$CONFIG_FILE" \
    --db=bolt \
    --bolt-path="$DATA_DIR/database.boltdb" \
    --tmp-path="$DATA_DIR/tmp" \
    --playbook-path="$DATA_DIR/playbooks" \
    --port=3000 \
    --admin="admin" \
    --admin-name="admin" \
    --admin-email="admin@example.com" \
    --admin-password="changeme"
fi

echo "[INFO] Starting Semaphore with persistent paths..."
exec /usr/local/bin/semaphore server --config="$CONFIG_FILE"