#!/bin/sh
set -eu

# ----- Required envs injected by Supervisor from config.json -----
: "${SEMAPHORE_DB_DIALECT:=bolt}"
: "${SEMAPHORE_DB_HOST:=/share/ansible_semaphore/database.boltdb}"
: "${SEMAPHORE_TMP_PATH:=/share/ansible_semaphore/tmp}"
: "${SEMAPHORE_PLAYBOOK_PATH:=/share/ansible_semaphore/playbooks}"
: "${SEMAPHORE_PORT:=3000}"

# Generate a key if not provided (needed by Semaphore)
: "${SEMAPHORE_ACCESS_KEY_ENCRYPTION:=}"
if [ -z "$SEMAPHORE_ACCESS_KEY_ENCRYPTION" ]; then
  if command -v openssl >/dev/null 2>&1; then
    SEMAPHORE_ACCESS_KEY_ENCRYPTION="$(openssl rand -hex 32)"
  else
    # Fallback if openssl not present in the base image
    SEMAPHORE_ACCESS_KEY_ENCRYPTION="$(dd if=/dev/urandom bs=32 count=1 2>/dev/null | od -An -tx1 | tr -d ' \n')"
  fi
fi

# ----- Validate DB path (fail fast if empty to avoid 'open : no such file') -----
if [ -z "${SEMAPHORE_DB_HOST:-}" ]; then
  echo "[ERROR] SEMAPHORE_DB_HOST resolved empty. Aborting." >&2
  env | grep -E '^SEMAPHORE_' || true
  exit 1
fi

# ----- Ensure persistence directories exist -----
PERSIST_DIR="/share/ansible_semaphore"
DB_DIR="$(dirname "$SEMAPHORE_DB_HOST")"

mkdir -p "$PERSIST_DIR" \
         "$DB_DIR" \
         "$SEMAPHORE_TMP_PATH" \
         "$SEMAPHORE_PLAYBOOK_PATH"

# Writability checks (fixes earlier silent RO failures)
for d in "$PERSIST_DIR" "$DB_DIR" "$SEMAPHORE_TMP_PATH" "$SEMAPHORE_PLAYBOOK_PATH"; do
  if [ ! -d "$d" ]; then
    echo "[ERROR] Required directory not present or not creatable: $d" >&2
    exit 1
  fi
  touch "$d/.ha-writetest" 2>/dev/null || {
    echo "[ERROR] Directory not writable: $d" >&2
    exit 1
  }
  rm -f "$d/.ha-writetest" 2>/dev/null || true
done

# ----- Locate semaphore binary inside the official image -----
BIN="$(command -v semaphore || true)"
if [ -z "$BIN" ]; then
  if [ -x /usr/local/bin/semaphore ]; then
    BIN="/usr/local/bin/semaphore"
  elif [ -x /usr/bin/semaphore ]; then
    BIN="/usr/bin/semaphore"
  fi
fi
if [ -z "$BIN" ] || [ ! -x "$BIN" ]; then
  echo "[ERROR] 'semaphore' binary not found in image." >&2
  which semaphore || true
  ls -l /usr/bin /usr/local/bin 2>/dev/null || true
  exit 1
fi

# ----- Log effective configuration so you can confirm values are not empty -----
echo "[INFO] Persistence:"
echo "  DB        : $SEMAPHORE_DB_HOST"
echo "  TMP       : $SEMAPHORE_TMP_PATH"
echo "  PLAYBOOKS : $SEMAPHORE_PLAYBOOK_PATH"
echo "  Port      : $SEMAPHORE_PORT"

# ----- Export envs for the server process -----
export SEMAPHORE_DB_DIALECT
export SEMAPHORE_DB_HOST
export SEMAPHORE_TMP_PATH
export SEMAPHORE_PLAYBOOK_PATH
export SEMAPHORE_PORT
export SEMAPHORE_ACCESS_KEY_ENCRYPTION

# ----- Start server WITHOUT a config file (use envs only) -----
echo "[INFO] Starting Semaphore (env-mode, --no-config) ..."
exec "$BIN" server --no-config