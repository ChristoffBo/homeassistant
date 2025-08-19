#!/usr/bin/env bash
set -euo pipefail

# Force all Semaphore data into Supervisor-persistent storage
export BASE="/data/semaphore"
export SEMAPHORE_CONFIG_PATH="$BASE"
export SEMAPHORE_TMP_PATH="$BASE/tmp"
export SEMAPHORE_PLAYBOOK_PATH="$BASE/playbooks"
export SEMAPHORE_DB_DIALECT="${SEMAPHORE_DB_DIALECT:-bolt}"
export SEMAPHORE_DB="${SEMAPHORE_DB:-$BASE/semaphore.db}"

# Create and ensure permissions for the current runtime user (root or non-root)
mkdir -p "$SEMAPHORE_CONFIG_PATH" "$SEMAPHORE_TMP_PATH" "$SEMAPHORE_PLAYBOOK_PATH"
chown -R "$(id -u)":"$(id -g)" "$BASE" || true

# Work from /data (supervisor-managed persistent dir)
cd /data

# Launch the upstream wrapper (correct path in the semaphore image)
exec /usr/local/bin/server-wrapper