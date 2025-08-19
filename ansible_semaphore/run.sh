#!/usr/bin/env bash
set -euo pipefail

# Logging helper
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" >&2
}

# Read environment variables provided by HA config.json
PORT="${PORT:-10443}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@example.com}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-changeme}"
DB_DIALECT="bolt"                     # Semaphore default lightweight DB
DB_PATH="/data/database.boltdb"
TMP_PATH="/tmp/semaphore"
PLAYBOOK_PATH="/data/playbooks"

# Warn if still using default password
if [[ "$ADMIN_PASSWORD" == "changeme" ]]; then
    log "WARNING: Using default password 'changeme'. Change it in your add-on options!"
fi

# Ensure required directories exist
mkdir -p /data "$PLAYBOOK_PATH" "$TMP_PATH"

log "Starting Semaphore..."
exec /usr/local/bin/semaphore server \
    --port="$PORT" \
    --tmp-path="$TMP_PATH" \
    --playbook-path="$PLAYBOOK_PATH" \
    --bolt-path="$DB_PATH" \
    --admin="$ADMIN_USER" \
    --admin-email="$ADMIN_EMAIL" \
    --admin-password="$ADMIN_PASSWORD"
