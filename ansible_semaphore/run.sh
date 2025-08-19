#!/bin/sh
set -e

echo "[INFO] Starting Ansible Semaphore add-on..."

# Ensure Supervisor mapped /share is writable and create our persistent dirs
PERSIST="/share/ansible_semaphore"
TMP="${SEMAPHORE_TMP_PATH:-/share/ansible_semaphore/tmp}"
PLAYBOOKS="${SEMAPHORE_PLAYBOOK_PATH:-/share/ansible_semaphore/playbooks}"
DB_FILE="${SEMAPHORE_DB_HOST:-/share/ansible_semaphore/database.boltdb}"
PORT="${SEMAPHORE_PORT:-3000}"

# Create required directories (no-op if they already exist)
mkdir -p "${PERSIST}" "${TMP}" "${PLAYBOOKS}"

echo "[INFO] Persistence:"
echo "       DB           : ${DB_FILE}"
echo "       TMP          : ${TMP}"
echo "       PLAYBOOKS    : ${PLAYBOOKS}"
echo "       Port (ingress): ${PORT}"
echo "       Admin        : ${SEMAPHORE_ADMIN:-admin} <${SEMAPHORE_ADMIN_EMAIL:-admin@example.com}>"

# Do not call `semaphore setup` (flags vary by version).
# The official image supports first-run bootstrap via environment variables:
#   SEMAPHORE_ADMIN, SEMAPHORE_ADMIN_EMAIL, SEMAPHORE_ADMIN_PASSWORD,
#   SEMAPHORE_DB_DIALECT=bolt, SEMAPHORE_DB_HOST, SEMAPHORE_TMP_PATH, SEMAPHORE_PLAYBOOK_PATH, SEMAPHORE_PORT
# Just run the server; it will initialize on first run using the env above.

# Start Semaphore
exec semaphore server