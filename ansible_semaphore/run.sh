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

# Read options
ADMIN_LOGIN="$(bashio::config 'admin_login')"
ADMIN_EMAIL="$(bashio::config 'admin_email')"
ADMIN_NAME="$(bashio::config 'admin_name')"
ADMIN_PASSWORD="$(bashio::config 'admin_password')"
CONF_PATH="$(bashio::config 'config_path')"
DATA_DIR="$(bashio::config 'data_dir')"
PORT="$(bashio::config 'port')"

# Basic sanity
: "${ADMIN_LOGIN:?admin_login missing in options}"
: "${ADMIN_PASSWORD:?admin_password missing in options}"
: "${CONF_PATH:?config_path missing in options}"
: "${DATA_DIR:?data_dir missing in options}"
: "${PORT:?port missing in options}"

# Ensure data dir exists and is writable
mkdir -p "${DATA_DIR}"
chown -R root:root "${DATA_DIR}" || true

# Show current config path
log "Config: ${CONF_PATH}"
log "Data  : ${DATA_DIR}"
log "Port  : ${PORT}"

# Ensure a minimal config exists if one isn't provided (BoltDB with HTTP on :3000)
if [ ! -s "${CONF_PATH}" ]; then
  log "No config file found; generating minimal BoltDB config."
  mkdir -p "$(dirname "${CONF_PATH}")"
  cat > "${CONF_PATH}" <<'JSON'
{
  "bolt": {
    "file": "/var/lib/semaphore/database.boltdb"
  },
  "tmp_path": "/tmp/semaphore",
  "cookie_hash": "change-me-cookie-hash",
  "cookie_encryption": "change-me-cookie-key",
  "access_key_encryption": "change-me-access-key",
  "web_host": "0.0.0.0",
  "web_port": "8055",
  "web_root": "",
  "non_auth": false
}
JSON
fi

# Make sure DB parent exists
mkdir -p /var/lib/semaphore

# Auto-provision / reset admin user from options
log "Ensuring admin user exists (or resetting password)..."
if ! semaphore user change-by-login \
  --login "${ADMIN_LOGIN}" \
  --password "${ADMIN_PASSWORD}" \
  --config "${CONF_PATH}"; then
  semaphore user add \
    --admin \
    --login "${ADMIN_LOGIN}" \
    --email "${ADMIN_EMAIL}" \
    --name  "${ADMIN_NAME}" \
    --password "${ADMIN_PASSWORD}" \
    --config "${CONF_PATH}"
fi
log "Admin ready: ${ADMIN_LOGIN}"

# Start server on configured port (override if needed)
export SEMAPHORE_PORT="${PORT}"
export SEMAPHORE_WEB_ROOT=""
log "Starting Semaphore on :${PORT}"
exec semaphore server --config "${CONF_PATH}"
