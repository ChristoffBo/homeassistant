#!/bin/sh
set -eu

# -------- Paths & options (read HA options if present) --------
PERSIST="/share/ansible_semaphore"
PORT="${PORT:-$(bashio::config 'port' 2>/dev/null || echo 3000)}"

ADMIN_USER="${SEMAPHORE_ADMIN:-$(bashio::config 'admin_user' 2>/dev/null || echo admin)}"
ADMIN_NAME="${SEMAPHORE_ADMIN_NAME:-$(bashio::config 'admin_name' 2>/dev/null || echo Administrator)}"
ADMIN_EMAIL="${SEMAPHORE_ADMIN_EMAIL:-$(bashio::config 'admin_email' 2>/dev/null || echo admin@example.com)}"
ADMIN_PASS="${SEMAPHORE_ADMIN_PASSWORD:-$(bashio::config 'admin_password' 2>/dev/null || echo changeme)}"

TMP="${SEMAPHORE_TMP_PATH:-$PERSIST/tmp}"
PROJECTS="${SEMAPHORE_PLAYBOOK_PATH:-$PERSIST/playbooks}"
DB_FILE="${SEMAPHORE_DB_FILE:-$PERSIST/database.boltdb}"   # final BoltDB file path
CFG="$PERSIST/config.json"

# Find the semaphore binary (official image installs in /usr/local/bin)
BIN="$(command -v semaphore || true)"
if [ -z "$BIN" ]; then
  BIN="/usr/local/bin/semaphore"
fi

echo "[INFO] Persistence:"
echo "  DB        : $DB_FILE"
echo "  TMP       : $TMP"
echo "  PLAYBOOKS : $PROJECTS"
echo "  Port      : $PORT"
echo "  Admin     : $ADMIN_USER <$ADMIN_EMAIL>"

# -------- Ensure persistent directories exist --------
mkdir -p "$PERSIST" "$TMP" "$PROJECTS"

# -------- Generate config.json on first run --------
if [ ! -f "$CFG" ]; then
  echo "[INFO] First run: generating $CFG"
  # Secrets (32 bytes hex)
  COOKIE_HASH="$(hexdump -vn32 -e '32/1 "%02x"' /dev/urandom 2>/dev/null || uuidgen | tr -d '-')"
  COOKIE_ENC="$(hexdump -vn32 -e '32/1 "%02x"' /dev/urandom 2>/dev/null || uuidgen | tr -d '-')"
  ACCESS_KEY_ENC="$(hexdump -vn32 -e '32/1 "%02x"' /dev/urandom 2>/dev/null || uuidgen | tr -d '-')"

  # NOTE: current Semaphore expects bolt host under "bolt.host"
  # Ref: official docs/config generator. 1
  cat > "$CFG" <<EOF
{
  "dialect": "bolt",
  "bolt": {
    "host": "$DB_FILE"
  },
  "tmp_path": "$TMP",
  "projects_path": "$PROJECTS",
  "cookie_hash": "$COOKIE_HASH",
  "cookie_encryption": "$COOKIE_ENC",
  "access_key_encryption": "$ACCESS_KEY_ENC",
  "server": {
    "port": "$PORT"
  }
}
EOF
  echo "[INFO] Wrote $CFG"
fi

# -------- Sanity checks --------
if [ ! -x "$BIN" ]; then
  echo "[ERROR] semaphore binary not found at $BIN" >&2
  ls -l /usr/local/bin || true
  exit 1
fi

# -------- Start server --------
echo "[INFO] Starting Semaphore ..."
exec "$BIN" server --config="$CFG"