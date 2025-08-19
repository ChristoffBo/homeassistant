#!/usr/bin/env bash
set -euo pipefail

echo "[INFO] Starting Ansible Semaphore add-on..."

# Writable, persistent base in HA add-ons
BASE="/share/semaphore"
TMP="$BASE/tmp"
PLAYBOOKS="$BASE/playbooks"
DB="$BASE/semaphore.db"

# Ensure persistence dirs exist
mkdir -p "$BASE" "$TMP" "$PLAYBOOKS"

# Pull options from Supervisor (if present)
OPTS="/data/options.json"
if [ -f "$OPTS" ]; then
  ADMIN_USER=$(jq -r '.admin_user // "admin"' "$OPTS")
  ADMIN_EMAIL=$(jq -r '.admin_email // "admin@example.com"' "$OPTS")
  ADMIN_PASS=$(jq -r '.admin_password // "changeme"' "$OPTS")
  LOG_LEVEL=$(jq -r '.log_level // "info"' "$OPTS")
  PORT=$(jq -r '.port // 10443' "$OPTS")
else
  ADMIN_USER="${SEMAPHORE_ADMIN:-admin}"
  ADMIN_EMAIL="${SEMAPHORE_ADMIN_EMAIL:-admin@example.com}"
  ADMIN_PASS="${SEMAPHORE_ADMIN_PASSWORD:-changeme}"
  LOG_LEVEL="${LOG_LEVEL:-info}"
  PORT="${PORT:-10443}"
fi

# Export the environment variables the official container uses to do first-run init
export LOG_LEVEL
export SEMAPHORE_DB_DIALECT="bolt"
export SEMAPHORE_DB="$DB"
export SEMAPHORE_ADMIN="$ADMIN_USER"
export SEMAPHORE_ADMIN_PASSWORD="$ADMIN_PASS"
export SEMAPHORE_ADMIN_NAME="Admin"
export SEMAPHORE_ADMIN_EMAIL="$ADMIN_EMAIL"
export SEMAPHORE_PLAYBOOK_PATH="$PLAYBOOKS"
export SEMAPHORE_TMP_PATH="$TMP"

echo "[INFO] DB: $SEMAPHORE_DB"
echo "[INFO] TMP: $SEMAPHORE_TMP_PATH"
echo "[INFO] PLAYBOOKS: $SEMAPHORE_PLAYBOOK_PATH"
echo "[INFO] Admin: $SEMAPHORE_ADMIN ($SEMAPHORE_ADMIN_EMAIL)"
echo "[INFO] Launching on port ${PORT} ..."

# Do NOT call `semaphore setup` (there is no --admin flag).
# The official image will auto-initialize on first run using the env vars above.
exec semaphore server --port "$PORT"
```0