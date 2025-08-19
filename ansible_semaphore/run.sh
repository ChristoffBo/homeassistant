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

# Logging function
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" >&2
}

# Error handling function
cleanup() {
    local exit_code=$?
    if [[ $exit_code -ne 0 ]]; then
        log "ERROR: Script failed with exit code $exit_code"
    fi
    exit $exit_code
}

# Set up error handling
trap cleanup EXIT

# Validate required environment variables
if [[ "$ADMIN_PASSWORD" == "changeme" ]]; then
    log "WARNING: Using default password 'changeme'. Please set ADMIN_PASSWORD environment variable!"
fi

# Create necessary directories
log "Creating required directories..."
mkdir -p /data "$PLAYBOOK_PATH" "$TMP_PATH"

# Check if Semaphore binary exists and is executable
if [[ ! -x "/usr/local/bin/semaphore" ]]; then
    log "ERROR: Semaphore binary not found or not executable at /usr/local/bin/semaphore"
    exit 1
fi

# Initialize Semaphore if config doesn't exist
if [[ ! -f "$CONFIG_PATH" ]]; then
    log "Configuration file not found. Initializing Semaphore with SQLite..."
    
    # Generate access key
    ACCESS_KEY=$(uuidgen)
    
    # Run semaphore setup with better error handling
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
    log "Admin user: $ADMIN_USER"
    log "Admin email: $ADMIN_EMAIL"
    log "Access key: $ACCESS_KEY"
    log "Port: $PORT"
else
    log "Found existing configuration at $CONFIG_PATH"
fi

# Validate configuration file
if [[ ! -r "$CONFIG_PATH" ]]; then
    log "ERROR: Configuration file $CONFIG_PATH is not readable"
    exit 1
fi

# Check database connectivity (basic check)
if [[ -f "$DB_PATH" ]]; then
    if ! sqlite3 "$DB_PATH" "SELECT 1;" >/dev/null 2>&1; then
        log "ERROR: Database file $DB_PATH appears to be corrupted"
        exit 1
    fi
    log "Database connectivity check passed"
fi

# Display configuration summary
log "Starting Ansible Semaphore with the following configuration:"
log "  Config file: $CONFIG_PATH"
log "  Database: $DB_PATH"
log "  Playbook path: $PLAYBOOK_PATH"
log "  Temporary path: $TMP_PATH"
log "  Port: $PORT"

# Start Semaphore server
log "Starting Semaphore server..."
exec /usr/local/bin/semaphore server --config "$CONFIG_PATH"
