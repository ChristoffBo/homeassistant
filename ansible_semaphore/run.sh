#!/usr/bin/env bash
set -euo pipefail
log() { echo "[semaphore-addon] $*"; }

# Ensure persistence dirs
mkdir -p /share/ansible_semaphore/{playbooks,tmp,keys,logs,config}
chmod -R 755 /share/ansible_semaphore || true

OPTS="/data/options.json"
jq -e . "$OPTS" >/dev/null 2>&1 || { log "options.json not ready"; exit 1; }

# Read options
export SEMAPHORE_DB_DIALECT="$(jq -r '.SEMAPHORE_DB_DIALECT' "$OPTS")"
export SEMAPHORE_DB_HOST="$(jq -r '.SEMAPHORE_DB_HOST' "$OPTS")"
export SEMAPHORE_PLAYBOOK_PATH="$(jq -r '.SEMAPHORE_PLAYBOOK_PATH' "$OPTS")"
export SEMAPHORE_TMP_PATH="$(jq -r '.SEMAPHORE_TMP_PATH' "$OPTS")"

export SEMAPHORE_ADMIN="$(jq -r '.SEMAPHORE_ADMIN' "$OPTS")"
export SEMAPHORE_ADMIN_NAME="$(jq -r '.SEMAPHORE_ADMIN_NAME' "$OPTS")"
export SEMAPHORE_ADMIN_EMAIL="$(jq -r '.SEMAPHORE_ADMIN_EMAIL' "$OPTS")"
export SEMAPHORE_ADMIN_PASSWORD="$(jq -r '.SEMAPHORE_ADMIN_PASSWORD' "$OPTS")"

export SEMAPHORE_COOKIE_HASH="$(jq -r '.SEMAPHORE_COOKIE_HASH' "$OPTS")"
export SEMAPHORE_COOKIE_ENCRYPTION="$(jq -r '.SEMAPHORE_COOKIE_ENCRYPTION' "$OPTS")"
export SEMAPHORE_ACCESS_KEY_ENCRYPTION="$(jq -r '.SEMAPHORE_ACCESS_KEY_ENCRYPTION' "$OPTS")"

export SEMAPHORE_PORT="$(jq -r '.SEMAPHORE_PORT' "$OPTS")"
export TZ="$(jq -r '.TZ' "$OPTS")"

# LDAP (optional)
LDAP_ENABLED_RAW="$(jq -r '.SEMAPHORE_LDAP_ACTIVATED // "no"' "$OPTS")"
export SEMAPHORE_LDAP_ENABLE=$( [ "$LDAP_ENABLED_RAW" = "yes" ] && echo "true" || echo "false" )
export SEMAPHORE_LDAP_SERVER="$(jq -r '.SEMAPHORE_LDAP_HOST // ""' "$OPTS")"
export SEMAPHORE_LDAP_NEEDTLS="$(jq -r '.SEMAPHORE_LDAP_NEEDTLS // "no"' "$OPTS")"
export SEMAPHORE_LDAP_BIND_DN="$(jq -r '.SEMAPHORE_LDAP_DN_BIND // ""' "$OPTS")"
export SEMAPHORE_LDAP_BIND_PASSWORD="$(jq -r '.SEMAPHORE_LDAP_PASSWORD // ""' "$OPTS")"
export SEMAPHORE_LDAP_SEARCH_DN="$(jq -r '.SEMAPHORE_LDAP_DN_SEARCH // ""' "$OPTS")"
export SEMAPHORE_LDAP_SEARCH_FILTER="$(jq -r '.SEMAPHORE_LDAP_SEARCH_FILTER // ""' "$OPTS")"

mkdir -p "$(dirname "$SEMAPHORE_DB_HOST")"

log "DB file: $SEMAPHORE_DB_HOST"
log "Admin user: $SEMAPHORE_ADMIN"

# --- Admin reset against old DB ---
RESET_CFG="/share/ansible_semaphore/config/reset-config.json"
cat > "$RESET_CFG" <<JSON
{
  "bolt": { "file": "${SEMAPHORE_DB_HOST}" },
  "tmp_path": "${SEMAPHORE_TMP_PATH}",
  "cookie_hash": "${SEMAPHORE_COOKIE_HASH}",
  "cookie_encryption": "${SEMAPHORE_COOKIE_ENCRYPTION}",
  "access_key_encryption": "${SEMAPHORE_ACCESS_KEY_ENCRYPTION}",
  "web_host": "",
  "web_port": "${SEMAPHORE_PORT}",
  "non_auth": false
}
JSON

if ! semaphore user change-by-login \
  --login "${SEMAPHORE_ADMIN}" \
  --password "${SEMAPHORE_ADMIN_PASSWORD}" \
  --config "$RESET_CFG"; then
  semaphore user add \
    --admin \
    --login "${SEMAPHORE_ADMIN}" \
    --email "${SEMAPHORE_ADMIN_EMAIL}" \
    --name  "${SEMAPHORE_ADMIN_NAME}" \
    --password "${SEMAPHORE_ADMIN_PASSWORD}" \
    --config "$RESET_CFG" || true
fi
log "Admin ensured/reset: ${SEMAPHORE_ADMIN}"

# Start Semaphore server
exec /usr/local/bin/server-wrapper