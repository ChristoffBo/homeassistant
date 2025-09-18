#!/usr/bin/env bash
# shellcheck shell=bash
set -euo pipefail

log() { echo "[semaphore-addon] $*"; }

# ─────────────────────────────────────────────
# Ensure bashio exists
if ! command -v bashio >/dev/null 2>&1; then
  log "bashio not found; this must be a HA add-on base image. Exiting."
  exit 1
fi

# ─────────────────────────────────────────────
# Best-effort package refresh on boot (won't fail if offline)
if command -v apt-get >/dev/null 2>&1; then
  (apt-get update || true) && (DEBIAN_FRONTEND=noninteractive apt-get -y upgrade || true)
fi

# ─────────────────────────────────────────────
# Read options from /data/options.json
PORT="$(bashio::config 'semaphore_port')"
DB_DIALECT="$(bashio::config 'semaphore_db_dialect')"
DB_HOST="$(bashio::config 'semaphore_db_host')"
TMP_PATH="$(bashio::config 'semaphore_tmp_path')"
PLAYBOOK_PATH="$(bashio::config 'semaphore_playbook_path')"

ADMIN_LOGIN="$(bashio::config 'semaphore_admin')"
ADMIN_NAME="$(bashio::config 'semaphore_admin_name')"
ADMIN_EMAIL="$(bashio::config 'semaphore_admin_email')"
ADMIN_PASSWORD="$(bashio::config 'semaphore_admin_password')"

COOKIE_HASH="$(bashio::config 'semaphore_cookie_hash')"
COOKIE_ENCRYPTION="$(bashio::config 'semaphore_cookie_encryption')"
ACCESS_KEY_ENCRYPTION="$(bashio::config 'semaphore_access_key_encryption')"

CONF_PATH="/etc/semaphore/config.json"

# ─────────────────────────────────────────────
# Basic checks
: "${DB_DIALECT:?db_dialect missing in options}"
: "${DB_HOST:?db_host missing in options}"
: "${PORT:?port missing in options}"

# ─────────────────────────────────────────────
# Ensure required dirs exist
mkdir -p "$(dirname "${CONF_PATH}")"
mkdir -p "${TMP_PATH}"
mkdir -p "${PLAYBOOK_PATH}"
mkdir -p "$(dirname "${DB_HOST}")"

# ─────────────────────────────────────────────
# Generate config.json dynamically
log "Writing Semaphore config: ${CONF_PATH}"
cat > "${CONF_PATH}" <<JSON
{
  "${DB_DIALECT}": {
    "file": "${DB_HOST}"
  },
  "tmp_path": "${TMP_PATH}",
  "cookie_hash": "${COOKIE_HASH}",
  "cookie_encryption": "${COOKIE_ENCRYPTION}",
  "access_key_encryption": "${ACCESS_KEY_ENCRYPTION}",
  "web_host": "0.0.0.0",
  "web_port": "${PORT}",
  "web_root": "",
  "playbook_path": "${PLAYBOOK_PATH}",
  "non_auth": false
}
JSON

# ─────────────────────────────────────────────
# Ensure admin user
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

# ─────────────────────────────────────────────
# Start Semaphore
log "Starting Semaphore on :${PORT} (DB: ${DB_DIALECT} @ ${DB_HOST})"
exec semaphore server --config "${CONF_PATH}"