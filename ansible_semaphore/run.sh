#!/usr/bin/env bash
set -euo pipefail

# Read options (provided by Supervisor at /data/options.json)
ADMIN_USER=$(jq -r '.admin_user' /data/options.json 2>/dev/null || echo "admin")
ADMIN_EMAIL=$(jq -r '.admin_email' /data/options.json 2>/dev/null || echo "admin@example.com")
ADMIN_PASSWORD=$(jq -r '.admin_password' /data/options.json 2>/dev/null || echo "changeme")
LOG_LEVEL=$(jq -r '.log_level // "info"' /data/options.json 2>/dev/null || echo "info")
ACCESS_KEY_ENCRYPTION=$(jq -r '.access_key_encryption // ""' /data/options.json 2>/dev/null || echo "")

PERSIST_ROOT="/share/ansible_semaphore"
DB_FILE="${PERSIST_ROOT}/database.boltdb"
TMP_DIR="${PERSIST_ROOT}/tmp"
PLAYBOOKS_DIR="${PERSIST_ROOT}/playbooks"

echo "[INFO] Ensuring persistent directories in ${PERSIST_ROOT} ..."
mkdir -p "${TMP_DIR}" "${PLAYBOOKS_DIR}"
# Create DB parent dir if missing (file will be created by Semaphore)
mkdir -p "$(dirname "${DB_FILE}")"

# If access key encryption not set, generate a stable value
if [ -z "${ACCESS_KEY_ENCRYPTION}" ] || [ "${ACCESS_KEY_ENCRYPTION}" = "null" ]; then
  ACCESS_KEY_ENCRYPTION=$(head -c32 /dev/urandom | base64)
  echo "[INFO] Generated SEMAPHORE_ACCESS_KEY_ENCRYPTION."
fi

# Export environment expected by Semaphore
export SEMAPHORE_DB_DIALECT="bolt"
export SEMAPHORE_DB_HOST="${DB_FILE}"
export SEMAPHORE_TMP_PATH="${TMP_DIR}"
export SEMAPHORE_PORT="3000"
export SEMAPHORE_ADMIN="${ADMIN_USER}"
export SEMAPHORE_ADMIN_EMAIL="${ADMIN_EMAIL}"
export SEMAPHORE_ADMIN_PASSWORD="${ADMIN_PASSWORD}"
export SEMAPHORE_ACCESS_KEY_ENCRYPTION="${ACCESS_KEY_ENCRYPTION}"
export LOG_LEVEL="${LOG_LEVEL}"

echo "[INFO] Starting Semaphore with:"
echo "       DB: ${SEMAPHORE_DB_DIALECT} -> ${SEMAPHORE_DB_HOST}"
echo "       TMP: ${SEMAPHORE_TMP_PATH}"
echo "       PORT: ${SEMAPHORE_PORT} (ingress)"
echo "       Admin: ${SEMAPHORE_ADMIN} <${SEMAPHORE_ADMIN_EMAIL}>"

# Start server (config comes from env vars)
exec /usr/bin/semaphore server