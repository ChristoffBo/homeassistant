#!/usr/bin/env bash
set -euo pipefail

echo "[INFO] Starting Ansible Semaphore add-on..."

# Persistent base (writable in HA add-ons)
BASE="/share/semaphore"
TMP="$BASE/tmp"
PLAYBOOKS="$BASE/playbooks"
DB="$BASE/semaphore.db"
CFG="$BASE/config.json"

# Ensure persistence dirs exist
mkdir -p "$BASE" "$TMP" "$PLAYBOOKS"

# Read options passed by Supervisor
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

export LOG_LEVEL
export SEMAPHORE_DB_DIALECT="bolt"
export SEMAPHORE_DB="$DB"
export SEMAPHORE_ADMIN="$ADMIN_USER"
export SEMAPHORE_ADMIN_EMAIL="$ADMIN_EMAIL"
export SEMAPHORE_ADMIN_PASSWORD="$ADMIN_PASS"
export SEMAPHORE_PLAYBOOK_PATH="$PLAYBOOKS"
export SEMAPHORE_TMP_PATH="$TMP"

# First-run bootstrap: create config and admin if DB missing
if [ ! -f "$DB" ]; then
  echo "[INFO] First run detected. Initializing Semaphore database & config..."
  semaphore setup \
    --admin "$SEMAPHORE_ADMIN" \
    --email "$SEMAPHORE_ADMIN_EMAIL" \
    --name "Home Assistant Admin" \
    --password "$SEMAPHORE_ADMIN_PASSWORD" \
    --db "$DB" \
    --tmp-path "$TMP" \
    --playbook-path "$PLAYBOOKS" \
    --config "$CFG"
else
  echo "[INFO] Existing DB found at $DB. Skipping setup."
  # Ensure config file exists (older versions may not have created it)
  if [ ! -f "$CFG" ]; then
    echo "[INFO] Generating missing config.json..."
    semaphore config \
      --db "$DB" \
      --tmp-path "$TMP" \
      --playbook-path "$PLAYBOOKS" > "$CFG"
  fi
fi

# Ensure port in config if needed (fallback: --port via env to server)
export PORT

echo "[INFO] Launching Semaphore on port ${PORT}..."
exec semaphore server --config "$CFG" --port "$PORT"