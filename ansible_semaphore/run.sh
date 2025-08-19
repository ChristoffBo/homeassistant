#!/bin/sh
set -eu

# ---------- Paths & options ----------
PERSIST="/share/ansible_semaphore"
PORT="${PORT:-$(bashio::config 'port' 2>/dev/null || echo 3000)}"

ADMIN_USER="${SEMAPHORE_ADMIN:-$(bashio::config 'admin_user' 2>/dev/null || echo admin)}"
ADMIN_NAME="${SEMAPHORE_ADMIN_NAME:-$(bashio::config 'admin_name' 2>/dev/null || echo Administrator)}"
ADMIN_EMAIL="${SEMAPHORE_ADMIN_EMAIL:-$(bashio::config 'admin_email' 2>/dev/null || echo admin@example.com)}"
ADMIN_PASS="${SEMAPHORE_ADMIN_PASSWORD:-$(bashio::config 'admin_password' 2>/dev/null || echo changeme)}"

TMP="${SEMAPHORE_TMP_PATH:-$PERSIST/tmp}"
PROJECTS="${SEMAPHORE_PLAYBOOK_PATH:-$PERSIST/playbooks}"
DB_FILE_DEFAULT="$PERSIST/database.boltdb"

# Prefer explicit envs if set; otherwise default
DB_FILE="${SEMAPHORE_DB_FILE:-${SEMAPHORE_DB:-$DB_FILE_DEFAULT}}"
CFG="$PERSIST/config.json"

# Resolve binary
BIN="$(command -v semaphore || true)"
[ -n "$BIN" ] || BIN="/usr/local/bin/semaphore"

echo "[INFO] Persistence:"
echo "  DB        : $DB_FILE"
echo "  TMP       : $TMP"
echo "  PLAYBOOKS : $PROJECTS"
echo "  Port      : $PORT"
echo "  Admin     : $ADMIN_USER <$ADMIN_EMAIL>"

# ---------- Ensure persistent dirs ----------
mkdir -p "$PERSIST" "$TMP" "$PROJECTS"

# ---------- Generate config.json on first run ----------
if [ ! -f "$CFG" ]; then
  echo "[INFO] First run: generating $CFG"

  # Secrets (32 bytes hex)
  gen_hex() { hexdump -vn32 -e '32/1 "%02x"' /dev/urandom 2>/dev/null || uuidgen | tr -d '-'; }
  COOKIE_HASH="$(gen_hex)"
  COOKIE_ENC="$(gen_hex)"
  ACCESS_KEY_ENC="$(gen_hex)"

  # Write both keys ('host' and 'file') to cover image variants
  cat > "$CFG" <<EOF
{
  "dialect": "bolt",
  "bolt": {
    "host": "$DB_FILE",
    "file": "$DB_FILE"
  },
  "tmp_path": "$TMP",
  "projects_path": "$PROJECTS",
  "cookie_hash": "$COOKIE_HASH",
  "cookie_encryption": "$COOKIE_ENC",
  "access_key_encryption": "$ACCESS_KEY_ENC",
  "server": { "port": "$PORT" }
}
EOF
  echo "[INFO] Wrote $CFG"
fi

# ---------- Force envs the official image reads (guards against empty) ----------
export SEMAPHORE_DB_DIALECT="bolt"
export SEMAPHORE_DB="$DB_FILE"                # legacy/primary env consumed by image
export SEMAPHORE_TMP_PATH="$TMP"
export SEMAPHORE_PLAYBOOK_PATH="$PROJECTS"
export SEMAPHORE_PORT="$PORT"

# Optional admin bootstrap (only if CLI supports it). If unsupported, UI can create.
# Uncomment if your image has this command:
# semaphore user add --login "$ADMIN_USER" --name "$ADMIN_NAME" --email "$ADMIN_EMAIL" --password "$ADMIN_PASS" --admin || true

# ---------- Sanity ----------
if [ ! -x "$BIN" ]; then
  echo "[ERROR] semaphore binary not found at: $BIN" >&2
  which semaphore || true
  ls -l /usr/local/bin || true
  exit 1
fi

# If DB path somehow resolved empty, fail fast (prevents 'open : no such file')
if [ -z "$DB_FILE" ]; then
  echo "[ERROR] DB_FILE resolved empty. Aborting." >&2
  exit 1
fi

# Ensure parent dir of DB exists (just in case)
mkdir -p "$(dirname "$DB_FILE")"

# ---------- Start ----------
echo "[INFO] Starting Semaphore ..."
exec "$BIN" server --config="$CFG"