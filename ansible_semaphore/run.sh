#!/bin/sh
set -eu

# ---------- Required env ----------
: "${SEMAPHORE_DB_DIALECT:=bolt}"
: "${SEMAPHORE_DB:=/share/ansible_semaphore/database.boltdb}"
: "${SEMAPHORE_TMP_PATH:=/share/ansible_semaphore/tmp}"
: "${SEMAPHORE_PLAYBOOK_PATH:=/share/ansible_semaphore/playbooks}"
: "${SEMAPHORE_PORT:=3000}"
: "${LOG_LEVEL:=info}"

# Admin seed (from config.json -> environment)
: "${SEED_ADMIN_USER:=admin}"
: "${SEED_ADMIN_NAME:=Admin User}"
: "${SEED_ADMIN_EMAIL:=admin@example.com}"
: "${SEED_ADMIN_PASSWORD:=changeme}"

# Encryption key (generate if empty)
: "${SEMAPHORE_ACCESS_KEY_ENCRYPTION:=}"
if [ -z "$SEMAPHORE_ACCESS_KEY_ENCRYPTION" ]; then
  if command -v openssl >/dev/null 2>&1; then
    SEMAPHORE_ACCESS_KEY_ENCRYPTION="$(openssl rand -hex 32)"
  else
    SEMAPHORE_ACCESS_KEY_ENCRYPTION="$(dd if=/dev/urandom bs=32 count=1 2>/dev/null | od -An -tx1 | tr -d ' \n')"
  fi
fi

# ---------- Ensure persistence ----------
PERSIST_DIR="/share/ansible_semaphore"
DB_DIR="$(dirname "$SEMAPHORE_DB")"

mkdir -p "$PERSIST_DIR" "$DB_DIR" "$SEMAPHORE_TMP_PATH" "$SEMAPHORE_PLAYBOOK_PATH"
for d in "$PERSIST_DIR" "$DB_DIR" "$SEMAPHORE_TMP_PATH" "$SEMAPHORE_PLAYBOOK_PATH"; do
  touch "$d/.w" 2>/dev/null || { echo "[ERROR] Not writable: $d"; exit 1; }
  rm -f "$d/.w" || true
done

# ---------- Find semaphore binary ----------
BIN="$(command -v semaphore || true)"
[ -n "$BIN" ] || { echo "[ERROR] semaphore binary not found in image"; exit 1; }

# ---------- Generate minimal config.json for CLI & server ----------
CFG="$PERSIST_DIR/config.json"
cat > "$CFG" <<EOF
{
  "interface": "",
  "port": "$SEMAPHORE_PORT",
  "tmp_path": "$SEMAPHORE_TMP_PATH",
  "projects_home": "$SEMAPHORE_TMP_PATH",
  "bolt": {
    "host": "$SEMAPHORE_DB"
  },
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

# ---------- Seed admin once (no terminal needed) ----------
DB_NEW=0
[ ! -s "$SEMAPHORE_DB" ] && DB_NEW=1

if [ "$DB_NEW" -eq 1 ]; then
  echo "[INFO] First boot: creating admin user '$SEED_ADMIN_USER'"
  # start server in the background so CLI can talk to DB layer if needed
  "$BIN" server --config "$CFG" >/tmp/semaphore-seed.log 2>&1 &
  SRV_PID=$!

  # wait until TCP is listening
  for i in $(seq 1 40); do
    sleep 0.5
    # if DB file appeared, we can try CLI directly via config
    [ -s "$SEMAPHORE_DB" ] && break
  done

  # create admin (idempotent: will fail if exists, which is fine)
  "$BIN" user add --admin \
    --login "$SEED_ADMIN_USER" \
    --name "$SEED_ADMIN_NAME" \
    --email "$SEED_ADMIN_EMAIL" \
    --password "$SEED_ADMIN_PASSWORD" \
    --config "$CFG" >/tmp/semaphore-useradd.log 2>&1 || true

  # stop the background server cleanly
  kill "$SRV_PID" >/dev/null 2>&1 || true
  wait "$SRV_PID" 2>/dev/null || true
fi

# ---------- Export env (server also reads config) ----------
export SEMAPHORE_DB_DIALECT SEMAPHORE_DB SEMAPHORE_TMP_PATH \
       SEMAPHORE_PLAYBOOK_PATH SEMAPHORE_PORT SEMAPHORE_ACCESS_KEY_ENCRYPTION

# ---------- Run server ----------
exec "$BIN" server --config "$CFG"