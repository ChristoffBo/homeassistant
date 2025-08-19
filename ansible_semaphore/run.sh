#!/usr/bin/env bash
set -e

echo "[INFO] Starting Semaphore with persistent paths..."

# Base persistent directory
BASE_DIR="/config/ansible_semaphore"

# Ensure persistence directories
mkdir -p "${BASE_DIR}/etc"
mkdir -p "${BASE_DIR}/lib"
mkdir -p "${BASE_DIR}/tmp"
mkdir -p "${BASE_DIR}/playbooks"

# Symlink into expected system paths
rm -rf /etc/semaphore && ln -s "${BASE_DIR}/etc" /etc/semaphore
rm -rf /var/lib/semaphore && ln -s "${BASE_DIR}/lib" /var/lib/semaphore
rm -rf /tmp/semaphore && ln -s "${BASE_DIR}/tmp" /tmp/semaphore

# Export admin defaults from config.json (HA add-on options)
ADMIN_USER=$(jq -r '.admin_username' /data/options.json)
ADMIN_PASS=$(jq -r '.admin_password' /data/options.json)
ADMIN_EMAIL=$(jq -r '.admin_email' /data/options.json)

export SEMAPHORE_ADMIN="${ADMIN_USER}"
export SEMAPHORE_ADMIN_PASSWORD="${ADMIN_PASS}"
export SEMAPHORE_ADMIN_NAME="Admin"
export SEMAPHORE_ADMIN_EMAIL="${ADMIN_EMAIL}"

# Initialize database if missing
if [ ! -f "${BASE_DIR}/lib/database.boltdb" ]; then
  echo "[INFO] First run detected, running setup..."
  semaphore setup \
    --config "${BASE_DIR}/etc/config.json" \
    --db "bolt://${BASE_DIR}/lib/database.boltdb" \
    --tmp-path "${BASE_DIR}/tmp" \
    --playbook-path "${BASE_DIR}/playbooks" \
    --cookie-secret "changeme_cookie_secret"
fi

echo "[INFO] Launching Semaphore..."
exec /usr/bin/semaphore server \
  --config "${BASE_DIR}/etc/config.json"