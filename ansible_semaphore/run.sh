#!/usr/bin/env sh
set -eu

# -------- Defaults (overridable by /data/options.json) --------
SEMAPHORE_DB_DIALECT="${SEMAPHORE_DB_DIALECT:-bolt}"
SEMAPHORE_DB="${SEMAPHORE_DB:-/share/ansible_semaphore/database.boltdb}"
SEMAPHORE_TMP_PATH="${SEMAPHORE_TMP_PATH:-/share/ansible_semaphore/tmp}"
SEMAPHORE_PLAYBOOK_PATH="${SEMAPHORE_PLAYBOOK_PATH:-/share/ansible_semaphore/playbooks}"
SEMAPHORE_PORT="8055"
LOG_LEVEL="info"

# Read HA options without jq (keep it simple)
if [ -f /data/options.json ]; then
  PORT_FROM_OPTIONS="$(sed -n 's/.*"port"[[:space:]]*:[[:space:]]*\([0-9]\+\).*/\1/p' /data/options.json | head -n1 || true)"
  [ -n "${PORT_FROM_OPTIONS:-}" ] && SEMAPHORE_PORT="$PORT_FROM_OPTIONS"
  LVL_FROM_OPTIONS="$(sed -n 's/.*"log_level"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' /data/options.json | head -n1 || true)"
  [ -n "${LVL_FROM_OPTIONS:-}" ] && LOG_LEVEL="$LVL_FROM_OPTIONS"
fi

case "$SEMAPHORE_PORT" in ''|*[!0-9]*)
  echo "[ERROR] Invalid port value: '$SEMAPHORE_PORT' — must be numeric." >&2
  exit 1
esac

# -------- Ensure persistence directories under /share --------
PERSIST_DIR="/share/ansible_semaphore"
DB_DIR="$(dirname "$SEMAPHORE_DB")"
mkdir -p "$PERSIST_DIR" "$DB_DIR" "$SEMAPHORE_TMP_PATH" "$SEMAPHORE_PLAYBOOK_PATH"

for d in "$PERSIST_DIR" "$DB_DIR" "$SEMAPHORE_TMP_PATH" "$SEMAPHORE_PLAYBOOK_PATH"; do
  [ -d "$d" ] || { echo "[ERROR] Missing directory: $d"; exit 1; }
  touch "$d/.ha-writetest" 2>/dev/null || { echo "[ERROR] Not writable: $d"; exit 1; }
  rm -f "$d/.ha-writetest" || true
done

# -------- Generate encryption key if not set --------
: "${SEMAPHORE_ACCESS_KEY_ENCRYPTION:=}"
if [ -z "$SEMAPHORE_ACCESS_KEY_ENCRYPTION" ]; then
  if command -v openssl >/dev/null 2>&1; then
    SEMAPHORE_ACCESS_KEY_ENCRYPTION="$(openssl rand -hex 32)"
  else
    SEMAPHORE_ACCESS_KEY_ENCRYPTION="$(dd if=/dev/urandom bs=32 count=1 2>/dev/null | od -An -tx1 | tr -d ' \n')"
  fi
fi

# -------- Locate Semaphore binary from image --------
BIN="$(command -v semaphore || true)"
[ -z "$BIN" ] && [ -x /usr/local/bin/semaphore ] && BIN="/usr/local/bin/semaphore"
[ -z "$BIN" ] && [ -x /usr/bin/semaphore ] && BIN="/usr/bin/semaphore"
if [ -z "$BIN" ] || [ ! -x "$BIN" ]; then
  echo "[ERROR] 'semaphore' binary not found in the image." >&2
  which semaphore || true
  ls -l /usr/bin /usr/local/bin 2>/dev/null || true
  exit 1
fi

# -------- Write a proper config.json for Semaphore --------
CFG="/share/ansible_semaphore/config.json"
cat > "$CFG" <<EOF
{
  "db": {
    "dialect": "bolt"
  },
  "bolt": {
    "host": "${SEMAPHORE_DB}"
  },
  "tmp_path": "${SEMAPHORE_TMP_PATH}",
  "playbook_path": "${SEMAPHORE_PLAYBOOK_PATH}",
  "access_key_encryption": "${SEMAPHORE_ACCESS_KEY_ENCRYPTION}",
  "web_host": "0.0.0.0",
  "port": "${SEMAPHORE_PORT}",
  "log_level": "${LOG_LEVEL}"
}
EOF

echo "[INFO] Persistence:"
echo "  DB        : $SEMAPHORE_DB"
echo "  TMP       : $SEMAPHORE_TMP_PATH"
echo "  PLAYBOOKS : $SEMAPHORE_PLAYBOOK_PATH"
echo "  Port      : $SEMAPHORE_PORT"
echo "  LogLevel  : $LOG_LEVEL"
echo "[INFO] Config     : $CFG"

# -------- Start server with explicit config --------
exec "$BIN" server --config "$CFG"