#!/bin/sh
set -e

echo "[semaphore-addon] Starting with official image"

# Ensure dirs exist
mkdir -p /share/ansible_semaphore/playbooks
touch /share/ansible_semaphore/semaphore.db

# Export environment for Semaphore
export SEMAPHORE_PORT="$(bashio::config 'semaphore_port' || echo 8055)"
export SEMAPHORE_DB_DIALECT="$(bashio::config 'semaphore_db_dialect' || echo sqlite)"
export SEMAPHORE_DB_HOST="$(bashio::config 'semaphore_db_host' || echo /share/ansible_semaphore/semaphore.db)"
export SEMAPHORE_TMP_PATH="$(bashio::config 'semaphore_tmp_path' || echo /tmp/semaphore)"
export SEMAPHORE_PLAYBOOK_PATH="$(bashio::config 'semaphore_playbook_path' || echo /share/ansible_semaphore/playbooks)"
export SEMAPHORE_ADMIN="$(bashio::config 'semaphore_admin' || echo admin)"
export SEMAPHORE_ADMIN_NAME="$(bashio::config 'semaphore_admin_name' || echo Admin)"
export SEMAPHORE_ADMIN_EMAIL="$(bashio::config 'semaphore_admin_email' || echo admin@example.com)"
export SEMAPHORE_ADMIN_PASSWORD="$(bashio::config 'semaphore_admin_password' || echo ChangeMe!123)"

echo "[semaphore-addon] DB: $SEMAPHORE_DB_DIALECT @ $SEMAPHORE_DB_HOST"
echo "[semaphore-addon] Admin: $SEMAPHORE_ADMIN / $SEMAPHORE_ADMIN_PASSWORD"

# Run official entrypoint
exec /usr/bin/semaphore server