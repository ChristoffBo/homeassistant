#!/usr/bin/env bash
set -euo pipefail

# Enable debug mode if DEBUG is set
if [[ "${DEBUG:-}" == "true" ]]; then
    set -x
fi

# Configuration from environment variables
readonly PORT="${PORT:-10443}"
readonly ADMIN_USER="${ADMIN_USER:-admin}"
readonly ADMIN_EMAIL="${ADMIN_EMAIL:-admin@example.com}"
readonly ADMIN_PASSWORD="${ADMIN_PASSWORD:-changeme}"
readonly DB_PATH="${DB_PATH:-/data/semaphore.db}"
readonly CONFIG_PATH="${CONFIG_PATH:-/data/semaphore_config.json}"
readonly PLAYBOOK_PATH="${PLAYBOOK_PATH:-/data/playbooks}"
readonly TMP_PATH="${TMP_PATH:-/tmp/semaphore}"

# Logging
log() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" >&2; }

cleanup() {
    local exit_code=$?
    if [[ $exit_code -ne 0 ]]; then
        log "ERROR: Script failed with exit code $exit_code"
    fi
    exit $exit_code
}
trap cleanup EXIT

if [[ "$ADMIN_PASSWORD" == "changeme" ]]; then
    log "WARNING: Using default password 'changeme'."
fi

log "Creating required directories..."
mkdir -p /data "$PLAYBOOK_PATH" "$TMP_PATH"

if [[ ! -x "/usr/local/bin/semaphore" ]]; then
    log "ERROR: Semaphore binary not found at /usr/local/bin/semaphore"
    exit 1
fi

if [[ ! -f "$CONFIG_PATH" ]]; then
    log "No config found. Initializing Semaphore with SQLite..."
    ACCESS_KEY=$(uuidgen)

    if ! /usr/local/bin/semaphore setup \
        --config "$CONFIG_PATH" \
        --db "sqlite3 $DB_PATH" \
        --admin "$ADMIN_USER" \
        --admin-email "$ADMIN_EMAIL" \
        --admin-password "$ADMIN_PASSWORD" \
        --access-key "$ACCESS_KEY" \
        --tmp-path "$TMP_PATH" \
        --playbook-path "$PLAYBOOK_PATH" \
        --port "$PORT"; then
        log "ERROR: Failed to initialize Semaphore"
        exit 1
    fi

    log "Semaphore initialized successfully!"
    log "Admin: $ADMIN_USER / $ADMIN_EMAIL"
    log "Port: $PORT"
else
    log "Found existing config at $CONFIG_PATH"
fi

if [[ -f "$DB_PATH" ]]; then
    if ! sqlite3 "$DB_PATH" "SELECT 1;" >/dev/null 2>&1; then
        log "ERROR: Database $DB_PATH looks corrupted"
        exit 1
    fi
    log "Database check passed"
fi

log "Starting Semaphore..."
exec /usr/local/bin/semaphore server --config "$CONFIG_PATH"
