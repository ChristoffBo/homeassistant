#!/bin/sh
set -eu

# ----- Required envs injected by Supervisor from config.json -----
: "${SEMAPHORE_DB_DIALECT:=bolt}"
: "${SEMAPHORE_DB:=/share/ansible_semaphore/database.boltdb}"
: "${SEMAPHORE_TMP_PATH:=/share/ansible_semaphore/tmp}"
: "${SEMAPHORE_PLAYBOOK_PATH:=/share/ansible_semaphore/playbooks}"
: "${SEMAPHORE_PORT:=3000}"

# ----- Validate DB path (fail fast if empty to avoid 'open : no such file') -----
if [ -z "$SEMAPHORE_DB" ]; then
  echo "[ERROR] SEMAPHORE_DB resolved empty. Aborting." >&2
  exit 1
fi

# ----- Ensure persistence directories exist -----
PERSIST_DIR="/share/ansible_semaphore"
DB_DIR="$(dirname "$SEMAPHORE_DB")"

mkdir -p "$PERSIST_DIR" \
         "$DB_DIR" \
         "$SEMAPHORE_TMP_PATH" \
         "$SEMAPHORE_PLAYBOOK_PATH"

# Extra safety: if any mkdir failed due to RO share, bail clearly
for d in "$PERSIST_DIR" "$DB_DIR" "$SEMAPHORE_TMP_PATH" "$SEMAPHORE_PLAYBOOK_PATH"; do
  if [ ! -d "$d" ]; then
    echo "[ERROR] Required directory not present or not creatable: $d" >&2
    exit 1
  fi
  # quick writability check
  touch "$d/.ha-writetest" 2>/dev/null || {
    echo "[ERROR] Directory not writable: $d" >&2
    exit 1
  }
  rm -f "$d/.ha-writetest" 2>/dev/null || true
done

# ----- Log what we will use -----
echo "[INFO] Persistence:"
echo "  DB        : $SEMAPHORE_DB"
echo "  TMP       : $SEMAPHORE_TMP_PATH"
echo "  PLAYBOOKS : $SEMAPHORE_PLAYBOOK_PATH"
echo "  Port      : $SEMAPHORE_PORT"

# ----- Locate semaphore binary inside the official image -----
BIN="$(command -v semaphore || true)"
if [ -z "$BIN" ]; then
  # Some tags place it under /usr/local/bin
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
export SEMAPHORE_DB
export SEMAPHORE_TMP_PATH
export SEMAPHORE_PLAYBOOK_PATH
export SEMAPHORE_PORT

# ----- Start server WITHOUT a --config file to avoid empty bolt path bugs -----
echo "[INFO] Starting Semaphore (env-mode, no config file) ..."
exec "$BIN" server