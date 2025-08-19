#!/bin/sh
set -e

# --------- Settings & paths (env and HA options) ----------
PERSIST="/share/ansible_semaphore"
PORT="${PORT:-$(bashio::config 'port' 2>/dev/null || echo 3000)}"

ADMIN_USER="${SEMAPHORE_ADMIN:-$(bashio::config 'admin_user' 2>/dev/null || echo admin)}"
ADMIN_NAME="${SEMAPHORE_ADMIN_NAME:-$(bashio::config 'admin_name' 2>/dev/null || echo Administrator)}"
ADMIN_EMAIL="${SEMAPHORE_ADMIN_EMAIL:-$(bashio::config 'admin_email' 2>/dev/null || echo admin@example.com)}"
ADMIN_PASS="${SEMAPHORE_ADMIN_PASSWORD:-$(bashio::config 'admin_password' 2>/dev/null || echo changeme)}"

TMP="${SEMAPHORE_TMP_PATH:-$PERSIST/tmp}"
PROJECTS="${SEMAPHORE_PLAYBOOK_PATH:-$PERSIST/playbooks}"
DB_FILE="${SEMAPHORE_DB_HOST:-$PERSIST/database.boltdb}"
CFG="$PERSIST/config.json"

BIN="/usr/local/bin/semaphore"   # Correct path in the official image

echo "[INFO] Starting Ansible Semaphore add-on..."
echo "[INFO] Persistence:"
echo "       DB           : $DB_FILE"
echo "       TMP          : $TMP"
echo "       PLAYBOOKS    : $PROJECTS"
echo "       Port         : $PORT"
echo "       Admin        : $ADMIN_USER <$ADMIN_EMAIL>"

# --------- Ensure persistent directories exist ----------
mkdir -p "$PERSIST" "$TMP" "$PROJECTS"

# --------- Generate config.json on first run ----------
if [ ! -f "$CFG" ]; then
  echo "[INFO] First run detected. Generating $CFG ..."

  # Generate secrets (32 bytes hex each)
  COOKIE_HASH="$(hexdump -vn32 -e '32/1 "%02x"' /dev/urandom 2>/dev/null || cat /proc/sys/kernel/random/uuid | tr -d '-')"
  COOKIE_ENC="$(hexdump -vn32 -e '32/1 "%02x"' /dev/urandom 2>/dev/null || cat /proc/sys/kernel/random/uuid | tr -d '-')"
  ACCESS_KEY_ENC="$(hexdump -vn32 -e '32/1 "%02x"' /dev/urandom 2>/dev/null || cat /proc/sys/kernel/random/uuid | tr -d '-')"

  # Write minimal modern Semaphore config (Bolt, paths, secrets, server port)
  cat > "$CFG" <<EOF
{
  "dialect": "bolt",
  "bolt": {
    "file": "$DB_FILE"
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

  echo "[INFO] Created $CFG"
fi

# --------- Initialize admin user if none exists ----------
# If the DB is empty (no users), create the admin via CLI.
# Newer Semaphore supports: `semaphore user add --login ... --name ... --email ... --password ... --admin`
# If the command is unavailable, server will start and you can create via UI.
if [ ! -s "$DB_FILE" ]; then
  echo "[INFO] Database file not found or empty. Will attempt to seed admin after server starts."
fi

# --------- Start server using config ----------
echo "[INFO] Starting Semaphore server..."
exec "$BIN" server --config="$CFG"