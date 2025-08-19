#!/bin/sh
set -euo pipefail

# --------- Required envs (from config.json environment) ----------
: "${SEMAPHORE_DB_DIALECT:=bolt}"
: "${SEMAPHORE_DB:=/share/ansible_semaphore/database.boltdb}"
: "${SEMAPHORE_TMP_PATH:=/share/ansible_semaphore/tmp}"
: "${SEMAPHORE_PLAYBOOK_PATH:=/share/ansible_semaphore/playbooks}"
: "${SEMAPHORE_PORT:=8055}"
: "${LOG_LEVEL:=info}"

# Generate encryption key if not set
: "${SEMAPHORE_ACCESS_KEY_ENCRYPTION:=}"
if [ -z "$SEMAPHORE_ACCESS_KEY_ENCRYPTION" ]; then
  if command -v openssl >/dev/null 2>&1; then
    SEMAPHORE_ACCESS_KEY_ENCRYPTION="$(openssl rand -hex 32)"
  else
    SEMAPHORE_ACCESS_KEY_ENCRYPTION="$(dd if=/dev/urandom bs=32 count=1 2>/dev/null | od -An -tx1 | tr -d ' \n')"
  fi
  export SEMAPHORE_ACCESS_KEY_ENCRYPTION
fi

# Validate DB path (avoid "open : no such file or directory")
if [ -z "${SEMAPHORE_DB}" ]; then
  echo "[ERROR] SEMAPHORE_DB resolved empty. Aborting." >&2
  env | grep -E '^SEMAPHORE_' || true
  exit 1
fi

# --------- Ensure persistence directories exist & writable ----------
PERSIST_DIR="/share/ansible_semaphore"
DB_DIR="$(dirname "$SEMAPHORE_DB")"

for d in "$PERSIST_DIR" "$DB_DIR" "$SEMAPHORE_TMP_PATH" "$SEMAPHORE_PLAYBOOK_PATH"; do
  mkdir -p "$d" || true
  if [ ! -d "$d" ]; then
    echo "[ERROR] Required directory not present or not creatable: $d" >&2
    exit 1
  fi
  touch "$d/.ha-writetest" 2>/dev/null || {
    echo "[ERROR] Directory not writable: $d" >&2
    exit 1
  }
  rm -f "$d/.ha-writetest" || true
done

# --------- Locate semaphore binary from official image ----------
BIN="$(command -v semaphore || true)"
if [ -z "$BIN" ]; then
  for c in /usr/local/bin/semaphore /usr/bin/semaphore; do
    [ -x "$c" ] && BIN="$c" && break
  done
fi
if [ -z "$BIN" ] || [ ! -x "$BIN" ]; then
  echo "[ERROR] 'semaphore' binary not found in image." >&2
  which semaphore || true
  ls -l /usr/bin /usr/local/bin 2>/dev/null || true
  exit 1
fi

# --------- Log effective config ----------
echo "[INFO] Persistence:"
echo "  DB        : $SEMAPHORE_DB"
echo "  TMP       : $SEMAPHORE_TMP_PATH"
echo "  PLAYBOOKS : $SEMAPHORE_PLAYBOOK_PATH"
echo "  Port      : $SEMAPHORE_PORT"
echo "  LogLevel  : $LOG_LEVEL"

# --------- Export envs for server (env-mode: --no-config) ----------
export SEMAPHORE_DB_DIALECT SEMAPHORE_DB SEMAPHORE_TMP_PATH SEM