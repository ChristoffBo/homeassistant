#!/usr/bin/env bash
set -euo pipefail
log() { echo "[semaphore-addon] $*"; }

CONFIG_PATH="/data/options.json"
CONF_PATH="/etc/semaphore/config.json"

# ─────────────────────────────────────────────
# Ensure jq is installed (official image has it, but just in case)
if ! command -v jq >/dev/null 2>&1; then
  log "jq missing, please add it to your Dockerfile (apt-get install -y jq)."
  exit 1
fi

# ─────────────────────────────────────────────
# Read options from /data/options.json
PORT="$(jq -r .semaphore_port "$CONFIG_PATH")"
DB_DIALECT="$(jq -r .semaphore_db_dialect "$CONFIG_PATH")"
DB_FILE="$(jq -r .semaphore_db_host "$CONFIG_PATH")"
TMP_PATH="$(jq -r .semaphore_tmp_path "$CONFIG_PATH")"
PLAYBOOK_PATH="$(jq -r .semaphore_playbook_path "$CONFIG_PATH")"

ADMIN_LOGIN="$(jq -r .semaphore_admin "$CONFIG_PATH")"
ADMIN_NAME="$(jq -r .semaphore_admin_name "$CONFIG_PATH")"
ADMIN_EMAIL="$(jq -r .semaphore_admin_email "$CONFIG_PATH")"
ADMIN_PASSWORD="$(jq -r .semaphore_admin_password "$CONFIG_PATH")"

COOKIE_HASH="$(jq -r .semaphore_cookie_hash "$CONFIG_PATH")"
COOKIE_ENCRYPTION="$(jq -r .semaphore_cookie_encryption "$CONFIG_PATH")"
ACCESS_KEY_ENCRYPTION="$(jq -r .semaphore_access_key_encryption "$CONFIG_PATH")"

# ─────────────────────────────────────────────
# Prepare dirs
mkdir -p "$(dirname "$CONF_PATH")" "$(dirname "$DB_FILE")" "$TMP_PATH" "$PLAYBOOK_PATH"

# ─────────────────────────────────────────────
# Generate config.json
log "Writing Semaphore config → $CONF_PATH"
cat > "$CONF_PATH" <<JSON
{
  "$DB_DIALECT": {
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

cat "$CONF_PATH"

# ─────────────────────────────────────────────
# Ensure admin user
log "Ensuring admin user exists (or resetting password)..."
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

log "Admin ready: $ADMIN_LOGIN"

# ─────────────────────────────────────────────
# Start server
log "Starting Semaphore on :$PORT using $DB_DIALECT @ $DB_FILE"
exec semaphore server --config "$CONF_PATH"