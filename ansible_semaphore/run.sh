#!/usr/bin/env sh
set -e

# Persistent dirs under /share (HA-writable)
DATA_DIR="/share/ansible_semaphore"
DB_FILE="${SEMAPHORE_DB:-$DATA_DIR/database.boltdb}"
TMP_DIR="${SEMAPHORE_TMP_PATH:-$DATA_DIR/tmp}"
PLAY_DIR="${SEMAPHORE_PLAYBOOK_PATH:-$DATA_DIR/playbooks}"

echo "[INFO] Persistence:"
echo "  DB        : $DB_FILE"
echo "  TMP       : $TMP_DIR"
echo "  PLAYBOOKS : $PLAY_DIR"
echo "  Port      : ${SEMAPHORE_PORT:-3000}"

# Ensure persistence exists
mkdir -p "$DATA_DIR" "$TMP_DIR" "$PLAY_DIR"

# If an empty DB path snuck in, fail loudly (prevents 'panic: open : no such file')
case "$DB_FILE" in
  ""|":") echo "[ERROR] SEMAPHORE_DB resolved empty. Set SEMAPHORE_DB to a file path." >&2; exit 1 ;;
esac

# Ensure parent dir for DB file exists
mkdir -p "$(dirname "$DB_FILE")"

# Export required env (server will use --no-config)
export SEMAPHORE_DB_DIALECT="${SEMAPHORE_DB_DIALECT:-bolt}"
export SEMAPHORE_DB="$DB_FILE"
export SEMAPHORE_TMP_PATH="$TMP_DIR"
export SEMAPHORE_PLAYBOOK_PATH="$PLAY_DIR"
export SEMAPHORE_PORT="${SEMAPHORE_PORT:-3000}"
export SEMAPHORE_ACCESS_KEY_ENCRYPTION="${SEMAPHORE_ACCESS_KEY_ENCRYPTION:-changeme}"

# The official image installs 'semaphore' on PATH (usually /usr/local/bin/semaphore)
if ! command -v semaphore >/dev/null 2>&1; then
  echo "[ERROR] 'semaphore' binary not found on PATH inside the container." >&2
  echo "        (Expected in the official image). Exiting." >&2
  exit 1
fi

echo "[INFO] Starting Semaphore (env-mode, --no-config) ..."
exec semaphore server --no-config