#!/usr/bin/env bash
set -euo pipefail
log() { echo "[semaphore-addon] $*"; }

# Load HA options
PORT="$(bashio::config 'semaphore_port')"
DB_DIALECT="$(bashio::config 'semaphore_db_dialect')"
DB_FILE="$(bashio::config 'semaphore_db_host')"
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
mkdir -p "$(dirname "$CONF_PATH")" "$(dirname "$DB_FILE")" "$TMP_PATH" "$PLAYBOOK_PATH"

# Write config.json
cat > "$CONF_PATH" <<JSON
{
  "sqlite": {
    "file": "$DB_FILE"
  },
  "tmp_path": "$TMP_PATH",
  "cookie_hash": "$COOKIE_HASH",
  "cookie_encryption": "$COOKIE_ENCRYPTION",
  "access_key_encryption": "$ACCESS_KEY_ENCRYPTION",
  "web_host": "0.0.0.0",
  "web_port": "$PORT",
  "web_root": "",
  "playbook_path": "$PLAYBOOK_PATH",
  "non_auth": false
}
JSON

log "Config written to $CONF_PATH:"
cat "$CONF_PATH"

# Ensure admin
if ! semaphore user change-by-login \
  --login "$ADMIN_LOGIN" \
  --password "$ADMIN_PASSWORD" \
  --config "$CONF_PATH"; then
  semaphore user add \
    --admin \
    --login "$ADMIN_LOGIN" \
    --email "$ADMIN_EMAIL" \
    --name  "$ADMIN_NAME" \
    --password "$ADMIN_PASSWORD" \
    --config "$CONF_PATH"
fi

log "Starting semaphore on :$PORT"
exec semaphore server --config "$CONF_PATH"