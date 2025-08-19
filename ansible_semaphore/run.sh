#!/usr/bin/env bash
set -euo pipefail

log() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" >&2; }

# Configuration via env variables
PORT="${PORT:-3000}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@example.com}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-changeme}"
DB_PATH="${DB_PATH:-/data/semaphore.db}"
CONFIG_PATH="${CONFIG_PATH:-/data/semaphore_config.json}"
PLAYBOOK_PATH="${PLAYBOOK_PATH:-/data/playbooks}"
TMP_PATH="${TMP_PATH:-/tmp/semaphore}"

trap 'exit_code=$?; (( exit_code != 0 )) && log "ERROR: Exit $exit_code"; exit $exit_code' EXIT

if [[ "$ADMIN_PASSWORD" == "changeme" ]]; then
    log "WARNING: Default password in use."
fi

log "Preparing directories..."
mkdir -p /data "$PLAYBOOK_PATH" "$TMP_PATH"

# Initialize if needed
if [[ ! -f "$CONFIG_PATH" ]]; then
    log "Initializing Semaphore with SQLite..."
    ACCESS_KEY=$(uuidgen)

    if ! /bin/semaphore setup \
        --config "$CONFIG_PATH" \
        --db "sqlite3 $DB_PATH" \
        --admin "$ADMIN_USER" \
        --admin-email "$ADMIN_EMAIL" \
        --admin-password "$ADMIN_PASSWORD" \
        --access-key "$ACCESS_KEY" \
        --tmp-path "$TMP_PATH" \
        --playbook-path "$PLAYBOOK_PATH" \
        --port "$PORT"; then
        log "ERROR: Setup failed"
        exit 1
    fi
    log "Initialized with admin=$ADMIN_USER, email=$ADMIN_EMAIL, port=$PORT"
else
    log "Using existing configuration."
fi

log "Starting Semaphore server..."
exec /bin/semaphore server --config "$CONFIG_PATH"
