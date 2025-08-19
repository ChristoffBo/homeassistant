#!/usr/bin/env bash
set -euo pipefail

# Debug mode
if [[ "${DEBUG:-}" == "true" ]]; then
    set -x
fi

readonly PORT="${PORT:-10443}"
readonly ADMIN_USER="${ADMIN_USER:-admin}"
readonly ADMIN_EMAIL="${ADMIN_EMAIL:-admin@example.com}"
readonly ADMIN_PASSWORD="${ADMIN_PASSWORD:-changeme}"
readonly DB_PATH="${DB_PATH:-/data/semaphore.db}"
readonly CONFIG_PATH="${CONFIG_PATH:-/data/semaphore_config.json}"
readonly PLAYBOOK_PATH="${PLAYBOOK_PATH:-/data/playbooks}"
readonly TMP_PATH="${TMP_PATH:-/tmp/semaphore}"

log() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" >&2; }

trap 'exit_code=$?; (( exit_code != 0 )) && log "ERROR: Exit $exit_code"; exit $exit_code' EXIT

if [[ "$ADMIN_PASSWORD" == "changeme" ]]; then
    log "WARNING: Default password in use."
fi

log "Creating necessary directories..."
mkdir -p /data "$PLAYBOOK_PATH" "$TMP_PATH"

if [[ ! -x "/usr/local/bin/semaphore" ]]; then
    log "ERROR: Semaphore binary not found"
    exit 1
fi

if [[ ! -f "$CONFIG_PATH" ]]; then
    log "Initializing Semaphore (SQLite)..."
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
        log "ERROR: Setup failed"
        exit 1
    fi
    log "Initialized: admin=${ADMIN_USER}, email=${ADMIN_EMAIL}, port=${PORT}"
else
    log "Existing config found: $CONFIG_PATH"
fi

if [[ -f "$DB_PATH" ]]; then
    if ! sqlite3 "$DB_PATH" "SELECT 1;" >/dev/null 2>&1; then
        log "ERROR: DB appears corrupted"
        exit 1
    fi
    log "Database healthy"
fi

log "Starting Semaphore server..."
exec /usr/local/bin/semaphore server --config "$CONFIG_PATH"
