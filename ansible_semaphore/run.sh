#!/usr/bin/env bash
# shellcheck shell=bash
set -euo pipefail

log() { echo "[semaphore-addon] $*"; }

# ────────────────────────────────
# bashio check (HA base image)
if ! command -v bashio >/dev/null 2>&1; then
  log "bashio not found; exiting."
  exit 1
fi

# ────────────────────────────────
# Optional apt update (safe)
if command -v apt-get >/dev/null 2>&1; then
  (apt-get update || true) && \
  (DEBIAN_FRONTEND=noninteractive apt-get -y upgrade || true)
fi

# ────────────────────────────────
# Load options from /data/options.json
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

# ────────────────────────────────
# Ensure paths exist
mkdir -p "$(dirname "${CONF_PATH}")" \
         "$(dirname "${DB_HOST}")" \
         "${TMP_PATH}" \
         "${PLAYBOOK_PATH}"

# ────────────────────────────────
# Write config.json dynamically
log "Writing Semaphore config (${DB_DIALECT}) -> ${CONF_PATH}"

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

log "Final config.json:"
cat "${CONF_PATH}"

# ────────────────────────────────
# Ensure admin user
log "Ensuring admin user exists..."
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

# ────────────────────────────────
# Start Semaphore
log "Starting Semaphore on :${PORT} (dialect=${DB_DIALECT})"
exec semaphore server --config "${CONF_PATH}"