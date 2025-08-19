#!/bin/sh
set -eu

# ---------- defaults ----------
: "${SEMAPHORE_DB_DIALECT:=bolt}"
: "${SEMAPHORE_DB:=/share/ansible_semaphore/database.boltdb}"
: "${SEMAPHORE_TMP_PATH:=/share/ansible_semaphore/tmp}"
: "${SEMAPHORE_PLAYBOOK_PATH:=/share/ansible_semaphore/playbooks}"

# Read options.json (HA injects add-on options here)
PORT_FROM_OPTIONS="$(sed -n 's/.*"port"[[:space:]]*:[[:space:]]*\([0-9]\{1,5\}\).*/\1/p' /data/options.json 2>/dev/null | head -n1 || true)"
LOG_FROM_OPTIONS="$(sed -n 's/.*"log_level"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' /data/options.json 2>/dev/null | head -n1 || true)"
ADMIN_USER="$(sed -n 's/.*"admin_user"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' /data/options.json 2>/dev/null | head -n1 || true)"
ADMIN_NAME="$(sed -n 's/.*"admin_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' /data/options.json 2>/dev/null | head -n1 || true)"
ADMIN_EMAIL="$(sed -n 's/.*"admin_email"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' /data/options.json 2>/dev/null | head -n1 || true)"
ADMIN_PASS="$(sed -n 's/.*"admin_password"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' /data/options.json 2>/dev/null | head -n1 || true)"

# Port & log level with sane fallbacks
SEMAPHORE_PORT="$PORT_FROM_OPTIONS"
echo "$SEMAPHORE_PORT" | grep -Eq '^[0-9]{1,5}$' || SEMAPHORE_PORT=3000
LOG_LEVEL="${LOG_FROM_OPTIONS:-info}"

# Seed admin defaults if blanks
: "${ADMIN_USER:=admin}"
: "${ADMIN_NAME:=Admin User}"
: "${ADMIN_EMAIL:=admin@example.com}"
: "${ADMIN_PASS:=changeme}"

# Encryption key
: "${SEMAPHORE_ACCESS_KEY_ENCRYPTION:=}"
if [ -z "$SEMAPHORE_ACCESS_KEY_ENCRYPTION" ]; then
  if command -v openssl >/dev/null 2>&1; then
    SEMAPHORE_ACCESS_KEY_ENCRYPTION="$(openssl rand -hex 32)"
  else
    SEMAPHORE_ACCESS_KEY_ENCRYPTION="$(dd if=/dev/urandom bs=32 count=1 2>/dev/null | od -An -tx1 | tr -d ' \n')"
  fi
fi

# ---------- persistence ----------
PERSIST_DIR="/share/ansible_semaphore"
DB_DIR="$(dirname "$SEMAPHORE_DB")"
mkdir -p "$PERSIST_DIR" "$DB_DIR" "$SEMAPHORE_TMP_PATH" "$SEMAPHORE_PLAYBOOK_PATH"
for d in "$PERSIST_DIR" "$DB_DIR" "$SEMAPHORE_TMP_PATH" "$SEMAPHORE_PLAYBOOK_PATH"; do
  touch "$d/.w" 2>/dev/null || { echo "[ERROR] Not writable: $d"; exit 1; }
  rm -f "$d/.w" || true
done

# ---------- find binary ----------
BIN="$(command -v semaphore || true)"
[ -n "$BIN" ] || { echo "[ERROR] semaphore binary not found in image"; exit 1; }

# ---------- write fresh config.json (never leaves placeholders) ----------
CFG="$PERSIST_DIR/config.json"
cat > "$CFG" <<EOF
{
  "interface": "",
  "port": "$SEMAPHORE_PORT",
  "tmp_path": "$SEMAPHORE_TMP_PATH",
  "projects_home": "$SEMAPHORE_TMP_PATH",
  "bolt": { "host": "$SEMAPHORE_DB" },
  "db_dialect": "$SEMAPHORE_DB_DIALECT",
  "dialect": "$SEMAPHORE_DB_DIALECT",
  "access_key_encryption": "$SEMAPHORE_ACCESS_KEY_ENCRYPTION",
  "log_level": "$LOG_LEVEL"
}
EOF

echo "[INFO] Persistence:
  DB        : $SEMAPHORE_DB
  TMP       : $SEMAPHORE_TMP_PATH
  PLAYBOOKS : $SEMAPHORE_PLAYBOOK_PATH
  Port      : $SEMAPHORE_PORT
  LogLevel  : $LOG_LEVEL
[INFO] Config     : $CFG"

# ---------- first-boot admin seed ----------
DB_NEW=0
[ ! -s "$SEMAPHORE_DB" ] && DB_NEW=1

if [ "$DB_NEW" -eq 1 ]; then
  echo "[INFO] First boot: creating admin user '$ADMIN_USER'"
  "$BIN" server --config "$CFG" >/tmp/semaphore-seed.log 2>&1 &
  SRV_PID=$!
  for i in $(seq 1 40); do
    [ -s "$SEMAPHORE_DB" ] && break
    sleep 0.5
  done
  "$BIN" user add --admin \
    --login "$ADMIN_USER" \
    --name "$ADMIN_NAME" \
    --email "$ADMIN_EMAIL" \
    --password "$ADMIN_PASS" \
    --config "$CFG" >/tmp/semaphore-useradd.log 2>&1 || true
  kill "$SRV_PID" >/dev/null 2>&1 || true
  wait "$SRV_PID" 2>/dev/null || true
fi

# ---------- start ----------
export SEMAPHORE_DB_DIALECT SEMAPHORE_DB SEMAPHORE_TMP_PATH \
       SEMAPHORE_PLAYBOOK_PATH SEMAPHORE_PORT SEMAPHORE_ACCESS_KEY_ENCRYPTION
exec "$BIN" server --config "$CFG"