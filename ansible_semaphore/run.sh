#!/usr/bin/env bash
# shellcheck shell=bash
set -euo pipefail

# Log helper
log() { echo "[semaphore-addon] $*"; }

# Wait for /data/options.json (bashio) to be ready
if ! command -v bashio >/dev/null 2>&1; then
  log "bashio not found; this must be a HA add-on base image. Exiting."
  exit 1
fi

# Best-effort package refresh on boot (won't fail if offline)
if command -v apt-get >/dev/null 2>&1; then
  (apt-get update || true) && (DEBIAN_FRONTEND=noninteractive apt-get -y upgrade || true)
fi

# Read options with defaults for ingress compatibility
ADMIN_LOGIN="$(bashio::config 'admin_login' 'admin')"
ADMIN_EMAIL="$(bashio::config 'admin_email' 'admin@example.com')"
ADMIN_NAME="$(bashio::config 'admin_name' 'Admin')"
ADMIN_PASSWORD="$(bashio::config 'admin_password' 'ChangeMe!123')"
CONF_PATH="$(bashio::config 'config_path' '/share/ansible_semaphore/config.json')"
DATA_DIR="$(bashio::config 'data_dir' '/share/ansible_semaphore')"

# Determine if ingress is enabled
if bashio::config.true 'ingress'; then
    PORT="8099"
    WEB_HOST="0.0.0.0"
    log "Ingress mode enabled - using port ${PORT}"
else
    PORT="$(bashio::config 'port' '8055')"
    WEB_HOST="0.0.0.0"
    log "Direct access mode - using port ${PORT}"
fi

# Basic sanity
: "${ADMIN_LOGIN:?admin_login missing}"
: "${ADMIN_PASSWORD:?admin_password missing}"
: "${CONF_PATH:?config_path missing}"
: "${DATA_DIR:?data_dir missing}"
: "${PORT:?port missing}"

# Ensure data dir exists and is writable
mkdir -p "${DATA_DIR}"
mkdir -p "$(dirname "${CONF_PATH}")"
mkdir -p /var/lib/semaphore
mkdir -p /tmp/semaphore
chown -R root:root "${DATA_DIR}" || true
chmod -R 755 "${DATA_DIR}" || true
chmod -R 755 /tmp/semaphore || true

# Show current config
log "Config: ${CONF_PATH}"
log "Data  : ${DATA_DIR}"
log "Port  : ${PORT}"

# Generate secure keys if not provided
COOKIE_HASH="$(bashio::config 'cookie_hash' "$(openssl rand -hex 32)")"
COOKIE_ENCRYPTION="$(bashio::config 'cookie_encryption' "$(openssl rand -hex 32)")"
ACCESS_KEY_ENCRYPTION="$(bashio::config 'access_key_encryption' "$(openssl rand -hex 32)")"

# Set ALL environment variables before doing anything
export SEMAPHORE_DB_DIALECT="bolt"
export SEMAPHORE_DB_PATH="${DATA_DIR}/database.boltdb"
export SEMAPHORE_TMP_PATH="/tmp/semaphore"
export SEMAPHORE_PORT="${PORT}"
export SEMAPHORE_WEB_ROOT=""
export SEMAPHORE_CONFIG_PATH="${CONF_PATH}"

# Clear any MySQL environment variables that might interfere
unset SEMAPHORE_DB_HOST 2>/dev/null || true
unset SEMAPHORE_DB_USER 2>/dev/null || true
unset SEMAPHORE_DB_PASS 2>/dev/null || true
unset SEMAPHORE_DB_NAME 2>/dev/null || true
unset SEMAPHORE_MYSQL_HOST 2>/dev/null || true
unset SEMAPHORE_MYSQL_USER 2>/dev/null || true
unset SEMAPHORE_MYSQL_PASS 2>/dev/null || true
unset SEMAPHORE_MYSQL_NAME 2>/dev/null || true

# Create minimal BoltDB config
log "Creating BoltDB configuration..."
cat > "${CONF_PATH}" <<EOF
{
  "dialect": "bolt",
  "tmp_path": "/tmp/semaphore",
  "cookie_hash": "${COOKIE_HASH}",
  "cookie_encryption": "${COOKIE_ENCRYPTION}",
  "access_key_encryption": "${ACCESS_KEY_ENCRYPTION}",
  "web_host": "${WEB_HOST}",
  "web_port": "${PORT}",
  "git_client": "go_git"
}
EOF

log "Configuration file created:"
cat "${CONF_PATH}"

# Initialize the database using environment variables only
log "Initializing database with environment variables..."
if [ ! -f "${DATA_DIR}/database.boltdb" ]; then
  log "Database file doesn't exist, running migration..."
  semaphore migrate --config "${CONF_PATH}" || log "Migration failed, continuing..."
fi

# Create admin user
log "Setting up admin user..."
semaphore user add \
  --admin \
  --login "${ADMIN_LOGIN}" \
  --email "${ADMIN_EMAIL}" \
  --name "${ADMIN_NAME}" \
  --password "${ADMIN_PASSWORD}" \
  --config "${CONF_PATH}" 2>/dev/null || log "User creation failed or user exists"

log "Admin ready: ${ADMIN_LOGIN}"

# Start server with explicit config
log "Starting Semaphore server..."
log "Using config: ${CONF_PATH}"
log "Database: ${DATA_DIR}/database.boltdb"
log "Port: ${PORT}"

exec semaphore server --config "${CONF_PATH}"
