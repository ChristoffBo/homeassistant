#!/bin/sh
set -eu

# ----- Required envs injected by Supervisor from config.json -----
: "${SEMAPHORE_DB_DIALECT:=bolt}"
: "${SEMAPHORE_DB_HOST:=/share/ansible_semaphore/database.boltdb}"
: "${SEMAPHORE_TMP_PATH:=/share/ansible_semaphore/tmp}"
: "${SEMAPHORE_PLAYBOOK_PATH:=/share/ansible_semaphore/playbooks}"
: "${SEMAPHORE_PORT:=3000}"

# ----- Validate DB path (fail fast if empty to avoid 'open : no such file') -----
if [ -z "$SEMAPHORE_DB_HOST" ]; then
  echo "[ERROR] SEMAPHORE_DB_HOST resolved empty. Aborting." >&2
  exit 1
fi

# ----- Ensure persistence directories exist -----
PERSIST_DIR="/share/ansible_semaphore"
DB_DIR="$(dirname "$SEMAPHORE_DB_HOST")"

mkdir -p "$PERSIST_DIR" \
         "$DB_DIR" \
         "$SEMAPHORE_TMP_PATH" \
         "$SEMAPHORE_PLAYBOOK_PATH"

# Extra safety: if any mkdir failed due to RO share, bail clearly
for d in "$PERSIST_DIR" "$DB_DIR" "$SEMAPHORE_TMP_PATH" "$SEMAPHORE_PLAYBOOK_PATH"; do
  if [ ! -d "$d" ]; then
    echo "[ERROR] Required directory not present or not creatable: $d" >&2
    exit 1
  }
  # quick writability check
  touch "$d/.ha-writetest" 2>/dev/null || {
    echo "[ERROR] Directory not writable: $d" >&2
    exit 1
  }
  rm -f "$d/.ha-writetest" 2>/dev/null || true
done

# ----- Log what we will use -----
echo "[INFO] Persistence:"
echo "  DB        : $SEMAPHORE_DB_HOST"
echo "  TMP       : $SEMAPHORE_TMP_PATH"
echo "  PLAYBOOKS : $SEMAPHORE_PLAYBOOK_PATH"
echo "  Port      : $SEMAPHORE_PORT"

# ----- Locate semaphore binary inside the official image -----
BIN="$(command -v semaphore || true)"
if [ -z "$BIN" ]; then
  if [ -x /usr/local/bin/semaphore ]; then
    BIN="/usr/local/bin/semaphore"
  fi
fi
if [ -z "$BIN" ] || [ ! -x "$BIN" ]; then
  echo "[ERROR] 'semaphore' binary not found in image." >&2
  which semaphore || true
  ls -l /usr/bin /usr/local/bin 2>/dev/null || true
  exit 1
fi

# ----- Export envs for the server process (image respects these) -----
export SEMAPHORE_DB_DIALECT
export SEMAPHORE_DB_HOST
export SEMAPHORE_TMP_PATH
export SEMAPHORE_PLAYBOOK_PATH
export SEMAPHORE_PORT

# ----- Start server WITHOUT a config file (use envs only) -----
echo "[INFO] Starting Semaphore (env-mode, --no-config) ..."
exec "$BIN" server --no-config