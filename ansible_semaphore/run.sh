#!/usr/bin/env bash
set -euo pipefail
log() { echo "[semaphore-addon] $*"; }

# Ensure persistence directories exist
mkdir -p /share/ansible_semaphore/{playbooks,tmp,keys,logs,config}
chmod -R 755 /share/ansible_semaphore || true

OPTS="/data/options.json"
jq -e . "$OPTS" >/dev/null 2>&1 || { log "options.json not ready"; exit 1; }

# Core settings
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

# LDAP mapping
LDAP_ENABLED_RAW="$(jq -r '.SEMAPHORE_LDAP_ACTIVATED // "no"' "$OPTS")"
export SEMAPHORE_LDAP_ENABLE=$( [ "$LDAP_ENABLED_RAW" = "yes" ] && echo "true" || echo "false" )
export SEMAPHORE_LDAP_SERVER="$(jq -r '.SEMAPHORE_LDAP_HOST // ""' "$OPTS")"
export SEMAPHORE_LDAP_NEEDTLS="$(jq -r '.SEMAPHORE_LDAP_NEEDTLS // "no"' "$OPTS")"
export SEMAPHORE_LDAP_BIND_DN="$(jq -r '.SEMAPHORE_LDAP_DN_BIND // ""' "$OPTS")"
export SEMAPHORE_LDAP_BIND_PASSWORD="$(jq -r '.SEMAPHORE_LDAP_PASSWORD // ""' "$OPTS")"
export SEMAPHORE_LDAP_SEARCH_DN="$(jq -r '.SEMAPHORE_LDAP_DN_SEARCH // ""' "$OPTS")"
export SEMAPHORE_LDAP_SEARCH_FILTER="$(jq -r '.SEMAPHORE_LDAP_SEARCH_FILTER // ""' "$OPTS")"

# Ensure DB dir exists
mkdir -p "$(dirname "$SEMAPHORE_DB_HOST")"

# Log summary
log "DB dialect  : ${SEMAPHORE_DB_DIALECT}"
log "DB file/host: ${SEMAPHORE_DB_HOST}"
log "Playbooks   : ${SEMAPHORE_PLAYBOOK_PATH}"
log "TMP path    : ${SEMAPHORE_TMP_PATH}"
log "Web port    : ${SEMAPHORE_PORT}"
log "Admin user  : ${SEMAPHORE_ADMIN}"

# Set defaults for Ansible
export ANSIBLE_HOST_KEY_CHECKING=false
export ANSIBLE_FORCE_COLOR=false
export ANSIBLE_LOG_PATH="/share/ansible_semaphore/logs/ansible.log"

# Start Semaphore using official wrapper
exec /usr/local/bin/server-wrapper